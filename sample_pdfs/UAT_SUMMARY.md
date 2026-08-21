# QORVENA · Iter102 UAT Summary

## Customer Invoice — Multi-Trip Consolidation
- Invoice number: **INV/26-27/1530**
- 4 customer trips, one per freight method:
  - **UAT-A1**  · Method: `per_ton_loading`  · Tons 20.0, Unloaded 19.7, Rate ₹1000
  - **UAT-A2**  · Method: `per_ton_unloading`  · Tons 25.0, Unloaded 24.6, Rate ₹1100
  - **UAT-A3**  · Method: `per_ton_higher_of`  · Tons 22.0, Unloaded 22.5, Rate ₹1200
  - **UAT-A4**  · Method: `fixed`  · Tons 18.0, Unloaded 18.0, Rate ₹32500

- **freight_total = ₹106,560.00**
- subtotal        = ₹98,560.00
- total_amount    = ₹98,560.00
- PDF: `sample_pdfs/uat_invoice_multi_trip.pdf`

## Supplier Statement — Cross-Check (UAT_DEMO_S_dd8446)
Trip-side totals (sum of persisted trip fields):
| Field | Total (₹) |
|---|---:|
| supplier_freight  | 190,300.00 |
| halting           | 0.00 |
| supplier_diesel   | 4,000.00 |
| supplier_advance  | 16,000.00 |
| supplier_shortage | 28,000.00 |
| **net_payable**   | **146,800.00** |

Statement JSON `totals` object matches trip aggregation to the paisa.
PDF: `sample_pdfs/uat_supplier_statement.pdf`
