"""`fixel setup`: save API keys to the Keychain, check them, and walk through macOS permissions."""

from __future__ import annotations

import getpass

from rich.console import Console

from . import permissions
from .config import Config, get_api_key, set_api_key, write_default_config


def _check_anthropic(key: str, model: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=1)
    try:
        client.models.retrieve(model)
        return f"[green]✔ Key works and {model} is available.[/]"
    except anthropic.AuthenticationError:
        return "[red]✖ Anthropic rejected this key.[/]"
    except anthropic.NotFoundError:
        ids = ", ".join(m.id for m in client.models.list(limit=20))
        return f"[yellow]! Key works, but '{model}' wasn't found. Available: {ids}. Update the models section of ~/.fixel/config.toml.[/]"
    except anthropic.APIConnectionError:
        return "[yellow]! Couldn't reach Anthropic to check the key (it's saved anyway).[/]"


def _check_gemini(key: str, model: str) -> str:
    from google import genai
    from google.genai import errors

    try:
        genai.Client(api_key=key).models.get(model=model)
        return f"[green]✔ Key works and {model} is available.[/]"
    except errors.APIError as e:
        if e.code == 404:
            return f"[yellow]! Key works, but '{model}' wasn't found. Update the models section of ~/.fixel/config.toml.[/]"
        return f"[red]✖ Google rejected this key ({e.code}).[/]"
    except Exception:
        return "[yellow]! Couldn't reach Google to check the key (it's saved anyway).[/]"


def _check_openai(key: str, model: str) -> str:
    import openai

    try:
        client = openai.OpenAI(api_key=key, max_retries=1)
        client.models.retrieve(model)
        return f"[green]✔ Key works and {model} is available.[/]"
    except openai.AuthenticationError:
        return "[red]✖ OpenAI rejected this key.[/]"
    except openai.NotFoundError:
        return f"[yellow]! Key works, but '{model}' wasn't found. Update the models section of ~/.fixel/config.toml.[/]"
    except openai.APIConnectionError:
        return "[yellow]! Couldn't reach OpenAI to check the key (it's saved anyway).[/]"
    except Exception as e:
        return f"[yellow]! Couldn't reach OpenAI to check the key: {e}[/]"


PROVIDERS = (
    ("anthropic", "Anthropic (Claude)", "sonnet", "https://console.anthropic.com/settings/keys", _check_anthropic),
    ("gemini", "Google Gemini (optional)", "gemini", "https://aistudio.google.com/apikey", _check_gemini),
    ("openai", "OpenAI (optional)", "gpt", "https://platform.openai.com/api-keys", _check_openai),
)


def check_api_key(vendor: str, key: str, model: str) -> str:
    checks = {
        "anthropic": _check_anthropic,
        "gemini": _check_gemini,
        "openai": _check_openai,
    }
    check = checks.get(vendor)
    if check is None:
        return f"[yellow]No automated check for '{vendor}'. Key is saved.[/]"
    return check(key, model)


def run_setup(cfg: Config, console: Console | None = None) -> None:
    console = console or Console()
    console.rule("[bold cyan]Fixel setup")
    if write_default_config(cfg):
        console.print(f"Created {cfg.config_path}")

    for vendor, label, alias, url, check in PROVIDERS:
        key = get_api_key(vendor)
        console.print(f"\n[bold]{label}[/]: key {'saved' if key else 'not set'}. Get one at {url}")
        entered = getpass.getpass("Paste key (hidden; press Enter to keep/skip): ").strip()
        if entered:
            set_api_key(vendor, entered)
            key = entered
            console.print("Saved to the macOS Keychain.")
        if key:
            model = cfg.models.get(alias, alias)
            console.print(check(key, model))

    app_name = permissions.host_app()
    console.print(f"\n[bold]Permissions[/] (macOS grants these to {app_name}):")
    checks = (
        ("Input Monitoring: the ⌥⌥ hotkey", permissions.input_monitoring_granted, permissions.request_input_monitoring, permissions.INPUT_MONITORING_URL),
        ("Screen Recording: screenshots", permissions.screen_recording_granted, permissions.request_screen_recording, permissions.SCREEN_RECORDING_URL),
    )
    for name, granted, request, url in checks:
        if granted():
            console.print(f"[green]✔ {name}[/]")
            continue
        request()
        permissions.open_settings(url)
        console.print(f"[yellow]! {name}: switch on {app_name} in the Settings page that just opened, then quit and reopen {app_name}.[/]")
    console.print("\nDone. Start Fixel with: [bold]fixel[/]")
