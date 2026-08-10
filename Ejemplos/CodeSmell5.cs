using System;

public class BankAccount
{
    public string Owner { get; set; }
    public decimal Balance { get; set; }
    public decimal OverdraftLimit { get; set; }
}

public class BankManager
{
    public bool CanWithdraw(BankAccount account, decimal amount)
    {
        if (account.Balance - amount >= -account.OverdraftLimit)
        {
            Console.WriteLine($"{account.Owner} can withdraw ${amount}.");
            return true;
        }

        Console.WriteLine($"{account.Owner} cannot withdraw ${amount}.");
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

        manager.CanWithdraw(account, 120);
        manager.CanWithdraw(account, 180);
    }
}