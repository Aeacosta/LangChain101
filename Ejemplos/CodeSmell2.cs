using System;

public class ShippingCalculator
{
    public decimal CalculateShipping(decimal orderTotal)
    {
        if (orderTotal > 100)
        {
            return 0;
        }

        if (orderTotal > 50)
        {
            return 5;
        }

        return 12;
    }
}

public class Program
{
    public static void Main()
    {
        var calculator = new ShippingCalculator();

        Console.WriteLine(calculator.CalculateShipping(120)); // 0
        Console.WriteLine(calculator.CalculateShipping(75));  // 5
        Console.WriteLine(calculator.CalculateShipping(30));  // 12
    }
}