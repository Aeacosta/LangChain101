using System;

public class BankAccount
{
    public string Owner { get; set; }
    public decimal Balance { get; private set; }
    public decimal OverdraftLimit { get; private set; }

    public bool CanWithdraw(decimal amount)
    {
        return Balance - amount >= -OverdraftLimit;
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

        bool canWithdrawLow = account.CanWithdraw(120);
        bool canWithdrawHigh = account.CanWithdraw(180);
    }
}

