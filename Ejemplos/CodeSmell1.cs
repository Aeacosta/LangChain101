using System;

public class UserManager
{
    public void RegisterUser(string name, string email)
    {
        // Validation
        if (string.IsNullOrWhiteSpace(name))
            throw new ArgumentException("Name is required.");

        if (!email.Contains("@"))
            throw new ArgumentException("Invalid email.");

        // Save user (simulated)
        Console.WriteLine($"Saving user '{name}' to the database...");

        // Send welcome email
        Console.WriteLine($"Sending welcome email to {email}...");
    }
}

public class Program
{
    public static void Main()
    {
        var userManager = new UserManager();
        userManager.RegisterUser("Alice", "alice@example.com");
    }
}