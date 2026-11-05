---
type: llm
focus: trace
weight: 1
---

The review identifies, as a blocking correctness issue with a line reference in shop/cart.py, that tax is computed on the undiscounted subtotal (the discount is subtracted after tax), so discounted orders pay too much tax.
