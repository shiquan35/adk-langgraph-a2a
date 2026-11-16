# Sales Data

This context describes the sales records used by the agents.

## Language

**Sales order**:
A sale represented by one product entry and identified by an `order_id`.
_Avoid_: Order line, transaction

**Order ID**:
The unique identifier of a sales order.
_Avoid_: Transaction ID

**Product**:
An item purchased in a sales order and assigned to one product category.
_Avoid_: Item (when referring to the catalog entity)

**Product category**:
A classification assigned to a product; a product has one canonical category. The current categories are Accessories, Audio, Displays, and Electronics.
_Avoid_: Type

**Sales region**:
A geographic grouping based on the customer's destination. The current regions are East, North, South, and West.
_Avoid_: Territory

**Order date**:
The calendar date on which the customer places the sales order.
_Avoid_: Transaction date

**Unit price**:
The amount charged for one unit of a product; the dataset does not specify a currency.
_Avoid_: Cost, order total
