// * A Special Class That Deals With User Specified Preferences And Uses It For The Rest Of The Program
using System;
using System.Windows.Forms;
using System.Drawing;

namespace Netflix
{
    public partial class UserPreferences : Form
    {
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        public static extern int SendMessage(IntPtr hWnd, int Msg, int wParam, int lParam);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        public static extern bool ReleaseCapture();

        private readonly PreferenceRepository repository;
        private readonly PreferenceSelector selector;
        public UserPreferences(Profile profile)
        {
            InitializeComponent();
            this.profile = profile;
            fileDirectory = Environment.CurrentDirectory + @"\Data\Profiles\" + profile.Account + @"\" + profile.User;
            fileProcesses();
            selectedLabels = new string[totalOptions];
            for (int i = 0; i < totalOptions; i++)
                selectedLabels[i] = "";
        }
        // La persistencia se delega a PreferenceRepository
        public void checkIfPreferencesPresent()
        {
            if (fileHandler.numberOfLines > 0)
            {
                this.Hide();
                MainPage mainPage = new MainPage(currentProfile, currentAccount, profileIndex);
                mainPage.Show();
            }
            else this.Show();
        }
        private void makeLog(string labelName, Genre genre)
        {
            if (count == preferenceLimit)
            {
                if (isLabelStored(labelName, genre))
                    return;
                MessageBox.Show("OOPs You Have Reached The Limit!");
                return;
            }
            if (isLabelStored(labelName, genre))
                return;
            if (selectedLabels[i] == "")
            {
                setIDImage(i, true);
                selectedLabels[i] = labelName;
                count++;
            }
        }
        // ? Boolean Type Refers to True if Selected & False For Unselected 
        private void setIDImage(int index, bool type)
        {
            string imageLocation = Environment.CurrentDirectory + @"\Data\Movie Titles\Genre Icons\";
            if (index < 0 || index >= genrePictures.Length) return;
            string fileName = type ? "Selected_" + genreNames[index] : genreNames[index];
            genrePictures[index].ImageLocation = imageLocation + fileName + ".png";
            genrePictures[index].SizeMode = PictureBoxSizeMode.Zoom;
                        ID3.ImageLocation = (imageLocation + "Drama.png");
                    else
                        ID3.ImageLocation = (imageLocation + "Selected_Drama.png");
                    ID3.SizeMode = PictureBoxSizeMode.Zoom;
                    break;
                case 4:
                    if (type == false)
                        ID4.ImageLocation = (imageLocation + "Comedy.png");
                    else
                        ID4.ImageLocation = (imageLocation + "Selected_Comedy.png");
                    ID4.SizeMode = PictureBoxSizeMode.Zoom;
                    break;
                case 5:
                    if (type == false)
                        ID5.ImageLocation = (imageLocation + "Horror.png");
                    else
                        ID5.ImageLocation = (imageLocation + "Selected_Horror.png");
                    ID5.SizeMode = PictureBoxSizeMode.Zoom;
                    break;
                case 6:
                    if (type == false)
                        ID6.ImageLocation = (imageLocation + "Romance.png");
                    else
                        ID6.ImageLocation = (imageLocation + "Selected_Romance.png");
                    ID6.SizeMode = PictureBoxSizeMode.Zoom;
                    break;
            }
        }
        private bool isLabelStored(string labelName, int i)
        {
            if (labelName == selectedLabels[i])
            {
                setIDImage(i, false);
                selectedLabels[i] = "";
                count--;
                return true;
            }
            return false;
        }
        private void storeLog()
        {
            for (int i = 0; i < totalOptions; i++)
                if (selectedLabels[i] != "")
                    f.WriteData(fileDirectory, selectedLabels[i]);
        }
        private void nextBtn_Click(object sender, EventArgs e)
        {
            if(count < minPreferences)
            {
                MessageBox.Show("Please select at least " + minPreferences + " " + "preferences!");
                return;
            }
            storeLog();
            this.Hide();
            MainPage f = new MainPage(profile);
            f.Show();
        }
        // Registrar en el Designer: pictureBox.Tag = i; and Wire Click once:
        private void Genre_Click(object sender, EventArgs e)
        {
            var box = (PictureBox)sender;
            int index = (int)box.Tag;
            makeLog(((Label)Controls["label" + index]).Text, index);
        }
        public const int WM_NCLBUTTONDOWN = 0xA1;
        public const int HT_CAPTION = 0x2;

        private void pictureBox2_Click(object sender, EventArgs e)
        {
            this.Hide();
            ProfilesHandling f = new ProfilesHandling(currentAccount);
            f.Show();
        }

        private void Form_MouseDown(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                ReleaseCapture();
                SendMessage(Handle, WM_NCLBUTTONDOWN, HT_CAPTION, 0);
            }
        }
        private void pictureBox3_MouseHover(object sender, EventArgs e)
        {
            pictureBox3.BackColor = Color.Red;
        }

        private void pictureBox3_MouseLeave(object sender, EventArgs e)
        {
            pictureBox3.BackColor = Color.Transparent;
        }

        private void ID0_Click(object sender, EventArgs e)
        {
            makeLog(label0.Text, Genre.Action);
        }

    }
}
    public enum Genre
    {
        Action = 0,
        Children = 1,
        Mystery = 2,
        Drama = 3,
        Comedy = 4,
        Horror = 5,
        Romance = 6
    }

            int i = (int)genre;
        const int minPreferences = 3;
