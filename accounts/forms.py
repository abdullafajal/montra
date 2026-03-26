"""Accounts forms — Registration, Login, Profile."""
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import UserProfile


tw = "w-full px-4 py-3 rounded-xl border border-m3-outline-variant dark:border-m3-outline-variant-dark bg-m3-surface-container-high dark:bg-m3-surface-container-high-dark text-m3-on-surface dark:text-m3-on-surface-dark focus:ring-2 focus:ring-m3-primary dark:focus:ring-m3-primary-dark focus:border-transparent outline-none transition-all duration-200"


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": tw, "placeholder": "Email address"}),
    )

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": tw, "placeholder": "Username"})
        self.fields["password1"].widget.attrs.update({"class": tw, "placeholder": "Password"})
        self.fields["password2"].widget.attrs.update({"class": tw, "placeholder": "Confirm password"})

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username or Email"
        self.fields["username"].widget.attrs.update({"class": tw, "placeholder": "Username or Email"})
        self.fields["password"].widget.attrs.update({"class": tw, "placeholder": "Password"})


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={"class": tw, "placeholder": "First name"}),
    )
    last_name = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={"class": tw, "placeholder": "Last name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": tw, "placeholder": "Email"}),
    )

    class Meta:
        model = UserProfile
        fields = ["currency", "theme", "email_reminders", "avatar"]
        widgets = {
            "currency": forms.Select(attrs={"class": tw}),
            "theme": forms.Select(attrs={"class": tw}),
            "email_reminders": forms.CheckboxInput(attrs={"class": "w-5 h-5 rounded border-m3-outline text-m3-primary focus:ring-m3-primary transition-all"}),
            "avatar": forms.FileInput(attrs={"class": tw}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields["first_name"].initial = self.user.first_name
            self.fields["last_name"].initial = self.user.last_name
            self.fields["email"].initial = self.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            if commit:
                self.user.save()
        if commit:
            profile.save()
        return profile


class ResendVerificationForm(forms.Form):
    """Simple form to collect email for resending verification."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": tw,
            "placeholder": "Enter your registered email",
        }),
    )


class ForgotPasswordForm(forms.Form):
    """Form to collect email for password reset."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": tw,
            "placeholder": "Enter your registered email",
        }),
    )


class SetNewPasswordForm(forms.Form):
    """Form to set a new password during reset."""
    password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            "class": tw,
            "placeholder": "New password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            "class": tw,
            "placeholder": "Confirm new password",
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data


