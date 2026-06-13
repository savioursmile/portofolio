"""
Portfolio Discord Bot
---------------------
Commands:
  /project add|remove|edit  — manage projects
  /donate add|remove        — manage donation links
  /reply <email> <message>  — reply to a contact form submission via email
  /status                   — show current site state

The bot talks to a tiny Flask API you deploy on Render (api.py).
Set these environment variables in Replit Secrets:
  DISCORD_TOKEN   — your bot token
  API_URL         — https://your-render-app.onrender.com
  API_SECRET      — shared secret between bot and API
  SMTP_HOST       — e.g. smtp.gmail.com
  SMTP_PORT       — 587
  SMTP_USER       — your email address
  SMTP_PASS       — your email password / app password
  FROM_EMAIL      — sender address shown to recipients
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import discord
from discord import app_commands
import aiohttp

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
API_URL       = os.environ["API_URL"].rstrip("/")
API_SECRET    = os.environ["API_SECRET"]
SMTP_HOST     = os.environ["SMTP_HOST"]
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASS     = os.environ["SMTP_PASS"]
FROM_EMAIL    = os.environ.get("FROM_EMAIL", SMTP_USER)

HEADERS = {"X-Secret": API_SECRET, "Content-Type": "application/json"}


# ── Discord client ────────────────────────────────────────────────────────────

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} — slash commands synced.")

bot = Bot()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def api(method: str, path: str, **kwargs):
    """Make an authenticated request to the Render API."""
    async with aiohttp.ClientSession() as session:
        fn = getattr(session, method)
        async with fn(f"{API_URL}{path}", headers=HEADERS, **kwargs) as r:
            return r.status, await r.json()


def send_email(to: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, to, msg.as_string())


def ok_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f" {title}", description=desc, color=0x57F287)

def err_embed(desc: str) -> discord.Embed:
    return discord.Embed(title="Error", description=desc, color=0xED4245)

def info_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=0xC861FF)


# ── /project ──────────────────────────────────────────────────────────────────

project_group = app_commands.Group(name="project", description="Manage portfolio projects")

@project_group.command(name="list", description="List all projects")
async def project_list(interaction: discord.Interaction):
    await interaction.response.defer()
    status, data = await api("get", "/projects")
    if status != 200:
        await interaction.followup.send(embed=err_embed("Could not reach API."))
        return
    projects = data.get("projects", [])
    if not projects:
        await interaction.followup.send(embed=info_embed("Projects", "No projects yet."))
        return
    lines = [f"**{i+1}.** `{p['id']}` — {p['title']}" for i, p in enumerate(projects)]
    await interaction.followup.send(embed=info_embed(f"Projects ({len(projects)})", "\n".join(lines)))


@project_group.command(name="add", description="Add a new project")
@app_commands.describe(
    title="Project title",
    description="Short description",
    tags="Comma-separated tags  e.g. React,Node.js",
    icon="Single emoji icon",
    span="Grid columns: 2, 3, or 4"
)
async def project_add(
    interaction: discord.Interaction,
    title: str,
    description: str,
    tags: str,
    icon: str = "💻",
    span: int = 2,
):
    await interaction.response.defer()
    payload = {
        "title": title,
        "description": description,
        "tags": [t.strip() for t in tags.split(",")],
        "icon": icon,
        "span": span,
    }
    status, data = await api("post", "/projects", json=payload)
    if status == 201:
        await interaction.followup.send(embed=ok_embed("Project added", f"**{title}** is now live on the site."))
    else:
        await interaction.followup.send(embed=err_embed(data.get("error", "Unknown error")))


@project_group.command(name="remove", description="Remove a project by ID")
@app_commands.describe(project_id="The project ID (use /project list to find it)")
async def project_remove(interaction: discord.Interaction, project_id: str):
    await interaction.response.defer()
    status, data = await api("delete", f"/projects/{project_id}")
    if status == 200:
        await interaction.followup.send(embed=ok_embed("Project removed", f"`{project_id}` has been deleted."))
    else:
        await interaction.followup.send(embed=err_embed(data.get("error", "Not found")))


@project_group.command(name="edit", description="Edit a project field")
@app_commands.describe(
    project_id="Project ID to edit",
    field="Field to change: title | description | tags | icon | span",
    value="New value (tags: comma-separated)"
)
async def project_edit(interaction: discord.Interaction, project_id: str, field: str, value: str):
    await interaction.response.defer()
    if field == "tags":
        parsed = [t.strip() for t in value.split(",")]
        payload = {"tags": parsed}
    elif field == "span":
        payload = {"span": int(value)}
    else:
        payload = {field: value}
    status, data = await api("patch", f"/projects/{project_id}", json=payload)
    if status == 200:
        await interaction.followup.send(embed=ok_embed("Project updated", f"`{project_id}` → `{field}` set to `{value}`."))
    else:
        await interaction.followup.send(embed=err_embed(data.get("error", "Unknown error")))


bot.tree.add_command(project_group)


# ── /donate ───────────────────────────────────────────────────────────────────

donate_group = app_commands.Group(name="donate", description="Manage donation links")

@donate_group.command(name="list", description="Show current donation options")
async def donate_list(interaction: discord.Interaction):
    await interaction.response.defer()
    status, data = await api("get", "/donate")
    if status != 200:
        await interaction.followup.send(embed=err_embed("Could not reach API."))
        return
    links = data.get("links", [])
    lines = [f"**{l['name']}** — {l['url']}  `{l['label']}`" for l in links]
    await interaction.followup.send(embed=info_embed("Donation links", "\n".join(lines) or "None set."))


@donate_group.command(name="set", description="Add or update a donation platform")
@app_commands.describe(
    name="Platform name e.g. Ko-fi",
    url="Full URL",
    label="Button label e.g. One-time support",
    icon="Single emoji"
)
async def donate_set(interaction: discord.Interaction, name: str, url: str, label: str, icon: str = "☕"):
    await interaction.response.defer()
    payload = {"name": name, "url": url, "label": label, "icon": icon}
    status, data = await api("post", "/donate", json=payload)
    if status in (200, 201):
        await interaction.followup.send(embed=ok_embed("Donation link saved", f"**{name}** → <{url}>"))
    else:
        await interaction.followup.send(embed=err_embed(data.get("error", "Unknown error")))


@donate_group.command(name="remove", description="Remove a donation platform by name")
@app_commands.describe(name="Platform name e.g. Ko-fi")
async def donate_remove(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    status, data = await api("delete", f"/donate/{name}")
    if status == 200:
        await interaction.followup.send(embed=ok_embed("Removed", f"**{name}** removed from the site."))
    else:
        await interaction.followup.send(embed=err_embed(data.get("error", "Not found")))


bot.tree.add_command(donate_group)


# ── /reply ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="reply", description="Reply to a contact form submission by email")
@app_commands.describe(
    to="Recipient email address",
    subject="Email subject line",
    message="Your reply message"
)
async def reply_cmd(interaction: discord.Interaction, to: str, subject: str, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        send_email(to, subject, message)
        await interaction.followup.send(
            embed=ok_embed("Email sent", f"Replied to **{to}**\nSubject: *{subject}*"),
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(embed=err_embed(f"SMTP error: {e}"), ephemeral=True)


# ── /status ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="status", description="Show a summary of the live site state")
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    s1, projects = await api("get", "/projects")
    s2, donate   = await api("get", "/donate")

    if s1 != 200 or s2 != 200:
        await interaction.followup.send(embed=err_embed("API unreachable — is Render up?"))
        return

    p_count = len(projects.get("projects", []))
    d_count = len(donate.get("links", []))

    embed = discord.Embed(title="📊 Site status", color=0xC861FF)
    embed.add_field(name="Projects", value=str(p_count), inline=True)
    embed.add_field(name="Donation links", value=str(d_count), inline=True)
    embed.add_field(name="API", value=f"[{API_URL}]({API_URL})", inline=False)
    await interaction.followup.send(embed=embed)


# ── Run ───────────────────────────────────────────────────────────────────────

bot.run(DISCORD_TOKEN)
