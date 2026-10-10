from sqlalchemy import Numeric

# Money and quantities: NUMERIC(24, 8). Never float.
Money = Numeric(24, 8)
Qty = Numeric(24, 8)
Price = Numeric(24, 10)
