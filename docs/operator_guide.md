# PromptDev: Operator Guide

*Managing system prompts, guardrails, and conversations*

---

## What This Guide Covers

1. Authentication and access
2. Dashboard overview
3. Managing personalities (system prompts)
4. Editing templates and versioning
5. Configuring guardrails
6. Monitoring conversations

---

## 1. Authentication

**URL:** `http://localhost:8001/`

All access requires admin login. Each admin (tenant) has isolated data - you only see your own templates, users, and conversations.

### First-Time Setup

```bash
# Create your admin account
make admin-create db=remote

# Enter email and password when prompted
```

### Login

Navigate to `http://localhost:8001/` and enter your credentials. Session lasts 24 hours.

### Admin Management

```bash
make admin-list db=remote                           # List all admins
make admin-reset-password db=remote email=...       # Reset password
make admin-activate db=remote email=...             # Re-enable admin
make admin-deactivate db=remote email=...           # Disable admin
```

---

## 2. Dashboard Overview

After login, you see three main views in the sidebar:

### Overview
Real-time statistics:
- **Active Users (Today/Hour):** How many users are chatting
- **Messages Today:** Total message count
- **Avg Response Time:** LLM latency in milliseconds
- **Error Rate:** Percentage of failed requests
- **Top Templates:** Most-used personalities

### Personalities
Manage system prompt templates. This is where you create and edit the prompts that define AI behavior.

### Conversations
Monitor active users. View conversation history, halt/resume chats, inject messages.

---

## 3. Managing Personalities

**Location:** Dashboard → Personalities

A "personality" is a system prompt template stored in the database. Each personality has:
- **Name:** Unique identifier
- **Content:** The actual prompt text (supports Jinja2 variables)
- **Version:** Auto-incremented on each edit
- **Status:** Active or Inactive

### Default Template

When you first login with no templates, the system automatically clones the default template for you.

### Creating a Personality

1. Click **+ New Personality**
2. Enter a unique name
3. Write the system prompt content
4. Enter your name/ID in "Created By"
5. Click **Create**

### Template Actions

| Action | What It Does |
|--------|-------------|
| **Edit** | Opens the template editor |
| **History** | Opens editor on version history tab |
| **Deactivate** | Prevents template from being used (doesn't delete) |
| **Activate** | Re-enables a deactivated template |
| **Delete** | Permanently removes template and all versions |

### Filtering

Use the dropdown to filter by:
- **All:** Show everything
- **Active:** Only usable templates
- **Inactive:** Only deactivated templates

---

## 4. Editing Templates

**Location:** Dashboard → Personalities → Edit

The editor has three tabs:

### Editor Tab

- **Template Name:** Read-only, set at creation
- **Template Content:** The system prompt (Jinja2 supported)
- **Change Description:** What you changed (saved in version history)
- **Updated By:** Your name/ID

Click **Save Changes** to create a new version. Every save creates a new version — content is never overwritten.

### Version History Tab

Shows all versions with:
- Version number
- Date/time created
- Who made the change
- Change description

**Actions:**
- **View Content:** See what that version contained
- **Rollback:** Restore that version's content (creates a new version)

### Preview Tab

Displays current template content. When viewing a historical version, shows that version.

### Jinja2 Variables

Templates support Jinja2 syntax for dynamic content:

```
You are {{ companion_name }}.

{% if user_context %}
User info: {{ user_context }}
{% endif %}

Your role is to {{ role_description }}.
```

Variables are filled in at runtime by the system.

---

## 5. Configuring Guardrails

Guardrails modify the system prompt before it's sent to the LLM. They prepend instructions that shape model behavior.

### How Guardrails Work

1. User sends a message
2. System loads the personality template
3. Guardrail rules are prepended to the template
4. Combined prompt is sent to LLM
5. LLM generates response

Guardrail instructions appear **before** your template content, so they take precedence.

### Preset Configs

| Config | Purpose |
|--------|---------|
| `unrestricted` | Removes safety restrictions — testing only |
| `research_safe` | Standard safety filters |
| `clinical` | Medical context, reduced disclaimers |

### Creating Custom Guardrail Configs

Currently done via API. Each config has:
- **Name:** Unique identifier
- **Description:** What this config does
- **Rules:** List of instructions with type and priority

### Rule Structure

```json
{
    "type": "system_instruction",
    "priority": 10,
    "content": "Your instruction text here"
}
```

- **type:** Currently only `system_instruction` is supported
- **priority:** Higher numbers are applied first (prepended earlier)
- **content:** The text to prepend

### Guardrail Strategies by Model

#### Dolphin Mistral (Local)

Dolphin is an "uncensored" model — it has minimal built-in refusals. This means:
- It will engage with almost any topic
- Your guardrails ARE the safety layer
- You need to explicitly tell it what NOT to do

**Recommended guardrail content for Dolphin:**

```
You engage openly with all relationship topics including conflict, 
intimacy, and difficult emotions. You never say "I cannot discuss" 
or refuse to help with sensitive personal topics.

You do NOT:
- Encourage abusive or controlling relationship behavior
- Reinforce self-harm or suicidal ideation
- Generate content sexualizing minors
- Provide instructions for illegal activities
```

#### Venice (Production)

Venice has moderate built-in caution. You may see occasional refusals on sensitive topics even when appropriate.

**If seeing unwanted refusals, add override instructions:**

```
You are permitted to discuss adult relationship topics directly 
and without excessive disclaimers. Do not refuse to engage with 
sensitive topics that are relevant to relationship practice.

When a topic seems sensitive, provide thoughtful engagement rather 
than refusing. Assume the user is an adult seeking genuine help.
```

### Guardrail Priority

Higher priority rules are prepended first (appear earlier in the final prompt):
- Priority 10 → prepended first
- Priority 5 → prepended after priority 10
- Priority 1 → prepended last (closest to your template)

---

## 6. Monitoring Conversations

**Location:** Dashboard → Conversations

### User List

Shows all users with recent activity:
- User ID
- Message count
- Last active time
- Current state (active/halted)

Click a user to open the monitor view.

### Monitor View

Displays the full conversation history for a user. Updates every 5 seconds.

**Sidebar shows:**
- Total messages
- Current state

### Intervention Actions

| Action | What It Does |
|--------|-------------|
| **Refresh** | Reload conversation immediately |
| **Inject Message** | Send a message as the AI (user sees it as AI response) |
| **Halt Conversation** | Block user from continuing (they see "conversation paused") |
| **Resume Conversation** | Unblock a halted user |
| **Export** | Download conversation as JSON |

### When to Intervene

- **Halt:** User is in crisis, conversation is going badly, safety concern
- **Inject:** Need to redirect conversation, provide information, or correct AI behavior
- **Resume:** After reviewing a halted conversation, if safe to continue

---

## 7. Multi-Tenant Isolation

Each admin (tenant) has completely isolated:
- Templates
- Users and conversations
- Guardrails
- Audit logs

You cannot see or access other admins' data. The system enforces `tenant_id` on all database queries.

### Template Sharing

Admins can optionally share templates:

1. Create template, mark `is_shareable = true`
2. Template appears in shared library
3. Other admin browses shared library, clicks "Clone"
4. Independent copy created in their space
5. Original and clone are completely independent

Lineage tracked via `cloned_from_id` and `cloned_from_tenant`.

---

## 8. Quick Reference

### Template Versioning

- Every edit creates a new version
- Old versions are never deleted
- Rollback creates a NEW version with old content
- Full audit trail maintained

### API Authentication

```bash
# Login and save session cookie
curl -X POST http://localhost:8001/admin/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword"}' \
  -c cookies.txt

# Use authenticated endpoints
curl http://localhost:8001/admin/templates -b cookies.txt

# Logout
curl -X POST http://localhost:8001/admin/logout -b cookies.txt
```

---

## Appendix: Future Features

The following capabilities are planned but not yet implemented:

- **Personas with Competing Objectives:** AI characters with primary and competing goals
- **Perturbations:** Adaptive challenges during conversations
- **Wellbeing Metrics:** Tracking sentiment and skill development
- **A/B Testing:** Compare template variants
- **Post-Generation Filtering:** Content evaluation after LLM generates response
- **Model Configuration Dashboard:** UI for managing multiple models

---

## Getting Help

- **Dashboard issues:** #ops-support
- **Prompt strategy questions:** #prompt-review  
- **Safety concerns:** Escalate immediately to safety lead
