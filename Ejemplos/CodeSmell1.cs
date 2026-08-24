using System;
// Asegurar los using/definiciones para IUserRepository, IEmailService y User

public class UserRegistrationService
{
    public void Register(string name, string email)
    {
        var user = User.Create(name, email); // centralizado
        _emailService.SendWelcome(user);
    }
}

public class Program
{
    public static void Main()
    {
        var service = new UserRegistrationService();
        service.Register("Alice", "alice@example.com");
    }
}

public class UserManager
{
    private readonly IUserRepository _userRepository;
    private readonly IEmailService _emailService;

    public UserManager(IUserRepository userRepository, IEmailService emailService)
    {
        _userRepository = userRepository;
        _emailService = emailService;
    }

    private void Validate(string name, string email)
    {
        if (string.IsNullOrWhiteSpace(name))
            throw new ArgumentException("El nombre es obligatorio", nameof(name));
        if (string.IsNullOrWhiteSpace(email))
            throw new ArgumentException("El email es obligatorio", nameof(email));
    }
}
        var user = new User(name, email);
