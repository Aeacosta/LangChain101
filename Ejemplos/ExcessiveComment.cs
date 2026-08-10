public class InvoiceCalculator
{
    // This method calculates the total amount of the invoice.
    // It loops through all the invoice items.
    // For each item, it multiplies the quantity by the price.
    // Then it adds the result to the running total.
    // Finally, it returns the total amount.
    public decimal CalculateTotal(List<InvoiceItem> items)
    {
        // Initialize total to zero.
        decimal total = 0;

        // Loop through every invoice item.
        foreach (var item in items)
        {
            // Multiply quantity by unit price.
            decimal subtotal = item.Quantity * item.UnitPrice;

            // Add subtotal to total.
            total += subtotal;
        }

        // Return the calculated total.
        return total;
    }

    // This method checks whether the invoice qualifies for a discount.
    // If the total is greater than 1000, a discount is applied.
    public bool HasDiscount(decimal total)
    {
        // Check if total exceeds threshold.
        return total > 1000;
    }
}