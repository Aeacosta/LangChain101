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
        _logger.Log(string.Format(Messages.SaveUser, user.Name));

        // Send welcome email
        _logger.Log(string.Format(Messages.SendWelcomeEmail, user.Email));
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