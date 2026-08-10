using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Mail;

public class ApplicationManager
{
    // User management
    private readonly List<User> _users = new();

    // Order management
    private readonly List<Order> _orders = new();

    // Logging
    private readonly string _logFile = "app.log";

    // Authentication
    private readonly Dictionary<string, string> _passwords = new();

    // ----------------------
    // User Management
    // ----------------------

    public void RegisterUser(string username, string password)
    {
        _users.Add(new User { Username = username });
        _passwords[username] = password;

        Log($"Registered user {username}");
        SendWelcomeEmail(username);
    }

    public User FindUser(string username)
    {
        return _users.Find(u => u.Username == username);
    }

    // ----------------------
    // Authentication
    // ----------------------

    public bool Login(string username, string password)
    {
        if (!_passwords.TryGetValue(username, out var stored))
            return false;

        Log($"User {username} attempted login");

        return stored == password;
    }

    // ----------------------
    // Orders
    // ----------------------

    public void CreateOrder(User user, decimal amount)
    {
        var order = new Order
        {
            Customer = user,
            Amount = amount,
            Created = DateTime.Now
        };

        _orders.Add(order);

        Log($"Created order for {user.Username}");
    }

    public decimal CalculateRevenue()
    {
        decimal total = 0;

        foreach (var order in _orders)
            total += order.Amount;

        return total;
    }

    // ----------------------
    // Reporting
    // ----------------------

    public void ExportOrdersCsv(string path)
    {
        using var writer = new StreamWriter(path);

        writer.WriteLine("Customer,Amount");

        foreach (var order in _orders)
        {
            writer.WriteLine($"{order.Customer.Username},{order.Amount}");
        }

        Log("Exported orders");
    }

    // ----------------------
    // Notifications
    // ----------------------

    public void SendWelcomeEmail(string username)
    {
        // Pretend email code
        Console.WriteLine($"Sending email to {username}");
    }

    public void SendMonthlyNewsletter()
    {
        foreach (var user in _users)
        {
            Console.WriteLine($"Newsletter sent to {user.Username}");
        }
    }

    // ----------------------
    // Logging
    // ----------------------

    public void Log(string message)
    {
        File.AppendAllText(_logFile,
            $"{DateTime.Now}: {message}{Environment.NewLine}");
    }

    // ----------------------
    // Backup
    // ----------------------

    public void BackupDatabase()
    {
        Console.WriteLine("Backing up database...");
    }

    public void RestoreDatabase()
    {
        Console.WriteLine("Restoring database...");
    }
}

public class User
{
    public string Username { get; set; }
}

public class Order
{
    public User Customer { get; set; }
    public decimal Amount { get; set; }
    public DateTime Created { get; set; }
}