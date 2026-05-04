#define UNICODE
#define _UNICODE
#define SECURITY_WIN32

#include <windows.h>
#include <security.h>
#include <iostream>
#include <string>

#pragma comment(lib, "Secur32.lib")
#pragma comment(lib, "Advapi32.lib")

std::wstring GetCurrentUsername()
{
    wchar_t buffer[256];
    DWORD size = 256;

    if (GetUserNameW(buffer, &size))
        return buffer;

    return L"UNKNOWN";
}

std::wstring GetCurrentDomainUsername()
{
    wchar_t buffer[512];
    ULONG size = 512;

    if (GetUserNameExW(NameSamCompatible, buffer, &size))
        return buffer;

    return L"UNKNOWN";
}

bool ValidateWindowsLogin(
    const std::wstring& domain,
    const std::wstring& username,
    const std::wstring& password
)
{
    HANDLE token = nullptr;

    BOOL ok = LogonUserW(
        username.c_str(),
        domain.empty() ? nullptr : domain.c_str(),
        password.c_str(),
        LOGON32_LOGON_INTERACTIVE,
        LOGON32_PROVIDER_DEFAULT,
        &token
    );

    if (ok)
    {
        CloseHandle(token);
        return true;
    }

    DWORD err = GetLastError();
    std::wcerr << L"LogonUserW failed. Error code: " << err << std::endl;
    return false;
}

int wmain()
{
    std::wcout << L"Current process user:" << std::endl;
    std::wcout << L"Username: " << GetCurrentUsername() << std::endl;
    std::wcout << L"Domain username: " << GetCurrentDomainUsername() << std::endl;

    std::wcout << L"\nValidate another Windows account" << std::endl;

    std::wstring domain;
    std::wstring username;
    std::wstring password;

    std::wcout << L"Domain or computer name, use . for local account: ";
    std::getline(std::wcin, domain);

    std::wcout << L"Username: ";
    std::getline(std::wcin, username);

    std::wcout << L"Password: ";
    std::getline(std::wcin, password);

    bool valid = ValidateWindowsLogin(domain, username, password);

    if (valid)
        std::wcout << L"\nLogin is VALID." << std::endl;
    else
        std::wcout << L"\nLogin is INVALID or not allowed." << std::endl;

    return 0;
}