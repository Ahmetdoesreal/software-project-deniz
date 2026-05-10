#define UNICODE
#define _UNICODE
#define SECURITY_WIN32

#include <windows.h>
#include <security.h>
#include <bcrypt.h>
#include <ctime>
#include <cstdio>
#include <iostream>
#include <string>

#pragma comment(lib, "Secur32.lib")
#pragma comment(lib, "Advapi32.lib")
#pragma comment(lib, "Bcrypt.lib")

// ── Helpers ───────────────────────────────────────────────────────────────────

static std::wstring GetCurrentDomainUsername()
{
    wchar_t buffer[512];
    ULONG size = 512;
    if (GetUserNameExW(NameSamCompatible, buffer, &size))
        return buffer;
    return L"UNKNOWN";
}

static std::wstring GetCurrentUsername()
{
    wchar_t buffer[256];
    DWORD size = 256;
    if (GetUserNameW(buffer, &size))
        return buffer;
    return L"UNKNOWN";
}

static bool ValidateWindowsLogin(
    const std::wstring& domain,
    const std::wstring& username,
    const std::wstring& password)
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
    if (ok) { CloseHandle(token); return true; }
    return false;
}

// ── BCrypt HMAC-SHA256 ────────────────────────────────────────────────────────
// Uses Windows CNG (built-in, no external libs).
// key     = shared auth secret (UTF-8 bytes)
// message = data to authenticate

static std::string HmacSha256Hex(const std::string& key, const std::string& message)
{
    BCRYPT_ALG_HANDLE  hAlg        = NULL;
    BCRYPT_HASH_HANDLE hHash       = NULL;
    PBYTE              pbHashObj   = NULL;
    DWORD              cbHashObj   = 0;
    DWORD              cbHash      = 0;
    DWORD              cbData      = 0;
    BYTE               hash[32]    = {};
    std::string        result;

    if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(
            &hAlg, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG)))
        goto done;

    if (!BCRYPT_SUCCESS(BCryptGetProperty(
            hAlg, BCRYPT_OBJECT_LENGTH,
            (PBYTE)&cbHashObj, sizeof(DWORD), &cbData, 0)))
        goto done;

    pbHashObj = (PBYTE)HeapAlloc(GetProcessHeap(), 0, cbHashObj);
    if (!pbHashObj) goto done;

    if (!BCRYPT_SUCCESS(BCryptGetProperty(
            hAlg, BCRYPT_HASH_LENGTH,
            (PBYTE)&cbHash, sizeof(DWORD), &cbData, 0)))
        goto done;

    if (!BCRYPT_SUCCESS(BCryptCreateHash(
            hAlg, &hHash, pbHashObj, cbHashObj,
            (PBYTE)key.data(), (ULONG)key.size(), 0)))
        goto done;

    if (!BCRYPT_SUCCESS(BCryptHashData(
            hHash, (PBYTE)message.data(), (ULONG)message.size(), 0)))
        goto done;

    if (!BCRYPT_SUCCESS(BCryptFinishHash(hHash, hash, cbHash, 0)))
        goto done;

    {
        char hex[65] = {};
        for (DWORD i = 0; i < cbHash && i < 32; i++)
            snprintf(hex + i * 2, 3, "%02x", hash[i]);
        result = hex;
    }

done:
    if (hHash)    BCryptDestroyHash(hHash);
    if (hAlg)     BCryptCloseAlgorithmProvider(hAlg, 0);
    if (pbHashObj) HeapFree(GetProcessHeap(), 0, pbHashObj);
    return result;
}

// ── Narrow helpers ────────────────────────────────────────────────────────────

static std::string WideToUtf8(const std::wstring& w)
{
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, NULL, 0, NULL, NULL);
    if (n <= 0) return {};
    std::string s(n - 1, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, &s[0], n, NULL, NULL);
    return s;
}

// ── Token generation ──────────────────────────────────────────────────────────
//
// token = HMAC-SHA256(secret, username_utf8 + "|" + time_window)
//
// time_window = Unix timestamp / 60  (rolls every 60 s)
// The Python server accepts window-1, window, window+1 to allow clock skew.

static std::string GenerateToken(const std::wstring& username, const std::wstring& secret)
{
    long long window = (long long)time(NULL) / 60;
    std::string uname  = WideToUtf8(username);
    std::string sec    = WideToUtf8(secret);
    std::string msg    = uname + "|" + std::to_string(window);
    return HmacSha256Hex(sec, msg);
}

// ── Entry point ───────────────────────────────────────────────────────────────

int wmain(int argc, wchar_t* argv[])
{
    // --whoami
    // Prints DOMAIN\username of the currently logged-in Windows user.
    if (argc >= 2 && wcscmp(argv[1], L"--whoami") == 0)
    {
        std::wcout << GetCurrentDomainUsername() << std::endl;
        return 0;
    }

    // --gen-token <domain> <username> <password> <shared_secret>
    // Validates AD credentials locally.  On success prints the HMAC token and
    // exits 0.  On failure exits 1 with no output so the password is never
    // transmitted over the network.
    if (argc >= 6 && wcscmp(argv[1], L"--gen-token") == 0)
    {
        std::wstring domain  = argv[2];
        std::wstring uname   = argv[3];
        std::wstring pass    = argv[4];
        std::wstring secret  = argv[5];

        if (!ValidateWindowsLogin(domain, uname, pass))
            return 1;

        std::string token = GenerateToken(uname, secret);
        if (token.empty())
            return 2;   // BCrypt failure

        std::cout << token << std::endl;
        return 0;
    }

    // --validate <domain> <username> <password>  (kept for manual testing)
    if (argc >= 5 && wcscmp(argv[1], L"--validate") == 0)
    {
        return ValidateWindowsLogin(argv[2], argv[3], argv[4]) ? 0 : 1;
    }

    // Interactive mode (manual testing)
    std::wcout << L"Current process user:" << std::endl;
    std::wcout << L"Username: " << GetCurrentUsername() << std::endl;
    std::wcout << L"Domain username: " << GetCurrentDomainUsername() << std::endl;

    std::wcout << L"\nValidate another Windows account" << std::endl;
    std::wstring domain, username, password;
    std::wcout << L"Domain (use . for local): "; std::getline(std::wcin, domain);
    std::wcout << L"Username: ";                 std::getline(std::wcin, username);
    std::wcout << L"Password: ";                 std::getline(std::wcin, password);

    if (ValidateWindowsLogin(domain, username, password))
        std::wcout << L"\nLogin is VALID." << std::endl;
    else
        std::wcout << L"\nLogin is INVALID or not allowed." << std::endl;

    return 0;
}
