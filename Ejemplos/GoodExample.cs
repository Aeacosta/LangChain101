using System.Linq;

public static class InvoiceCalculator
{
    // Constante nombrada elimina el Magic Number y facilita su cambio.
    private const decimal DiscountThreshold = 1000m;

    /// <summary>
    /// Calcula el total de una factura sumando cantidad * precio unitario de cada ítem.
    /// </summary>
    public static decimal CalculateTotal(IEnumerable<InvoiceItem> items) =>
        items.Sum(item => item.Quantity * item.UnitPrice);

    /// <summary>
    /// Indica si el total dado supera el umbral para aplicar un descuento.
    /// </summary>
    public static bool IsEligibleForDiscount(decimal total) =>
        total > DiscountThreshold;
}