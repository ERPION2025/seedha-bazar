from django.test import TestCase

from storage import wdra
from storage.models import Warehouse
from storage.services import warehouses_near

FORM = '''<select class="form-control" id="x" name="_in_gov_wdra_warehouse_publiclist_portlet_WarehousePubliclistPortlet_INSTANCE_faio_selectStateName" name="x">
<option value="">Select State</option><option value="23">Madhya Pradesh
</option><option value="-1">All</option></select>
<form action="https://wdra.gov.in/registered-wh-public?p_p_id=x&amp;p_auth=abc" method="POST">'''
TABLE = '''<table id="resultTableId"><thead><tr><th>WHM Name</th></tr></thead><tbody>
<tr> <td>ARTI GANGOLIA</td> <td>Astik Warehouse</td> <td>6825483</td> <td>Vill- Bamhori Deori</td> <td>Raisen</td> <td>Madhya Pradesh</td> <td>10000</td> <td>26-Dec-2023</td> <td>25-Dec-2028</td> <td>7773000624</td> <td>Active</td> <td></td> </tr>
<tr> <td>KAILASH SHARMA</td> <td>SHYAM WAREHOUSE</td> <td>6993786</td> <td>GRAM PAGRANI</td> <td>Rewa</td> <td>Madhya Pradesh</td> <td>5699</td> <td>12-Nov-2024</td> <td>11-Nov-2029</td> <td>9826318650</td> <td>Inactive</td> <td>INSUFFICIENT INSURANCE</td> </tr>
<tr> <td>R K</td> <td>Laxmi Warehouse</td> <td>7000001</td> <td>Rewa road</td> <td>Rewa</td> <td>Madhya Pradesh</td> <td>12000</td> <td>15-Apr-2025</td> <td>15-Apr-2030</td> <td>9000000000</td> <td>Active</td> <td></td> </tr>
</tbody></table>'''


class FakeSession:
    def __init__(self, tables):
        self.tables, self.posts = tables, []

    def get(self, url):
        return FORM

    def post(self, url, data):
        self.posts.append(data)
        return FORM + self.tables.pop(0)


class WdraTests(TestCase):
    def test_form_and_table_are_read(self):
        codes, action = wdra.states_and_action(FORM)
        self.assertEqual(codes, {"Madhya Pradesh": "23"})
        self.assertIn("p_auth=abc", action)
        rows = wdra.parse_table(TABLE)
        self.assertEqual((len(rows), rows[1]["status"], rows[1]["remarks"]), (3, "Inactive", "INSUFFICIENT INSURANCE"))

    def test_sync_saves_updates_and_marks_what_drops_off(self):
        s = FakeSession([TABLE, TABLE.replace("<tr> <td>R K</td>", "<tr class='x'> <td>R K</td>")])
        [run] = wdra.sync_states(["Madhya Pradesh"], pause=0, session=s)
        self.assertEqual((run.ok, run.rows, run.added), (True, 3, 3))
        w = Warehouse.objects.get(wdra_reg_no="6825483")
        self.assertEqual((w.name, w.district, w.capacity_mt, w.valid_until.year, w.verified), ("Astik Warehouse", "Raisen", 10000, 2028, True))
        [run2] = wdra.sync_states(["Madhya Pradesh"], pause=0, session=s)
        self.assertEqual((run2.added, run2.updated, run2.gone), (0, 2, 1))
        self.assertEqual(Warehouse.objects.get(wdra_reg_no="7000001").wdra_status, "Not listed")

    def test_farmers_see_active_ones_first(self):
        wdra.save_state("Madhya Pradesh", wdra.parse_table(TABLE))
        near, _ = warehouses_near("Madhya Pradesh", "Rewa")
        self.assertEqual([w.name for w in near], ["Laxmi Warehouse", "SHYAM WAREHOUSE"])

    def test_a_failed_state_is_recorded_and_the_rest_continue(self):
        s = FakeSession(["<html>maintenance</html>"])
        [run] = wdra.sync_states(["Madhya Pradesh"], pause=0, session=s)
        self.assertFalse(run.ok)
        self.assertIn("No result table", run.error)
        self.assertFalse(wdra.due())  # retried after an hour, not at once
