public class InvoiceCalculator
{
    public decimal CalculateTotal(List<InvoiceItem> items)
    {
        decimal total = 0;

        foreach (var item in items)
        {
            decimal subtotal = item.Quantity * item.UnitPrice;

            total += subtotal;
        }

        return total;
    }

    public bool HasDiscount(decimal total)
    {
        return total > DiscountThreshold;
    }
}

    private const decimal DiscountThreshold = 1000m;

