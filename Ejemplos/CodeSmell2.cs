using System;

public class Program
{
    public static void Main()
    {
        var calculator = new ShippingCalculator();

    private const int LargeOrderAmount = 120;
    private const int MediumOrderAmount = 75;
    private const int SmallOrderAmount = 30;

        Console.WriteLine(calculator.CalculateShipping(LargeOrderAmount));  // 0
        Console.WriteLine(calculator.CalculateShipping(MediumOrderAmount)); // 5
        Console.WriteLine(calculator.CalculateShipping(SmallOrderAmount));  // 12
    }
}