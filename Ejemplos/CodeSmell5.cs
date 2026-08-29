using System;

public class BankAccount
{
    public string Owner { get; set; }
    public decimal Balance { get; set; }
    public decimal OverdraftLimit { get; set; }
}

public class BankManager
{

    public bool CanWithdraw(decimal amount)
    {
        if (Balance - amount >= -OverdraftLimit)
        {
            Console.WriteLine($"{Owner} can withdraw ${amount}.");
            return true;
        }

        Console.WriteLine($"{Owner} cannot withdraw ${amount}.");
        return false;
    }
}

public class Program
{
    public static void Main()
    {
        var account = new BankAccount
        {
            Owner = "Alice",
            Balance = 100,
            OverdraftLimit = 50
        };

        var manager = new BankManager();

        account.CanWithdraw(120);
        account.CanWithdraw(180);
    }
}