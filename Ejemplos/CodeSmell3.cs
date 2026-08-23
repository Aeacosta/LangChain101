public class CustomerService
{
    private string customerName;
    private int age;
    private bool isActive;
    private decimal balance;
    private List<Order> orders;

    public void UpdateCustomer(
        string name,
        int age,
        bool active)
    {
        this.customerName = name;
        this.age = age;
        this.isActive = active;
    }
}    public void Activate() => IsActive = true;    public void Deactivate() => IsActive = false;    public void UpdateProfile(string name, int age)    {        if (string.IsNullOrWhiteSpace(name))            throw new ArgumentException("name");        if (age < 0)            throw new ArgumentException("age");        Name = name;        Age = age;    }