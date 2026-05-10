import aiohttp


async def perform_login(
    base_url: str,
    login_id: str,
    password: str,
    *,
    ad_domain: str | None = None,
    ad_secret: str | None = None,
) -> str:
    """
    Log in and return the session UUID.

    Normal mode:  sends {login_id, password} to the server.
    AD mode:      validates credentials locally via check_user.exe, then sends
                  {login_id, token} — the real password never leaves this machine.

    Raises ValueError on login failure.
    """
    if ad_domain is not None and ad_secret is not None:
        from auth_util.ad_auth import generate_token
        token = generate_token(ad_domain, login_id, password, ad_secret)
        if token is None:
            raise ValueError("AD authentication failed. Check your username, password, and domain.")
        send_credential = token
    else:
        send_credential = password

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url}/login",
            json={"login_id": login_id, "password": send_credential},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["uuid"]
            body = await resp.text()
            raise ValueError(f"Login failed ({resp.status}): {body}")


async def check_health(base_url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/health") as resp:
            data = await resp.json()
            print(f"[HTTP] Health: {data}")
