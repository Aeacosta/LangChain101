public class CustomerService
{
    private string strCustomerName;
    private int iCustomerAge;
    private bool bIsActive;
    private decimal decBalance;
    private List<Order> lstOrders;

    public void UpdateCustomer(
        string strName,
        int iAge,
        bool bActive)
    {
        strCustomerName = strName;
        iCustomerAge = iAge;
        bIsActive = bActive;
    }
}