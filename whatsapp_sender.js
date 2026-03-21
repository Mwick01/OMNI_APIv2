// whatsapp_sender.js
// Reads unsent notices from SQLite and sends them to WhatsApp channel

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const sqlite3 = require("better-sqlite3");
const path = require("path");
const fs = require("fs");

const CHANNEL_ID = process.env.WHATSAPP_CHANNEL_ID;
const DB_PATH = path.join(__dirname, "database.db");

// ── Verify session exists before doing anything ───────────────────────────────
const sessionPath = ".wwebjs_auth/session";
const indexedDbPath = ".wwebjs_auth/session/Default/IndexedDB";

console.log("🔍 Checking session...");
console.log("  Session folder exists:", fs.existsSync(sessionPath));
console.log("  IndexedDB exists:", fs.existsSync(indexedDbPath));

if (!fs.existsSync(sessionPath)) {
  console.error("❌ No session found. Run auth workflow first.");
  process.exit(1);
}

const db = new sqlite3(DB_PATH);

function getUnsentNotices() {
  return db.prepare("SELECT * FROM notices WHERE sent_to_whatsapp = 0").all();
}

function markAsSent(id) {
  db.prepare("UPDATE notices SET sent_to_whatsapp = 1 WHERE id = ?").run(id);
}

function buildCaption(notice) {
  const { title, url, date_on_site } = notice;
  const cleanTitle = title.replace(/Download\s*$/i, "").trim();
  return [
    "📢 *New Notice*",
    "",
    `📌 *${cleanTitle}*`,
    `🕐 ${date_on_site}`,
    `🔗 ${url}`,
  ].join("\n");
}

async function sendNotices(client) {
  const unsent = getUnsentNotices();

  if (unsent.length === 0) {
    console.log("📭 No new notices to send.");
    return;
  }

  console.log(`📤 Sending ${unsent.length} notice(s)...`);

  for (const notice of unsent) {
    const { id, file_path } = notice;
    const caption = buildCaption(notice);

    try {
      const ext = path.extname(file_path || "").toLowerCase();
      const fileExists = file_path && fs.existsSync(file_path);

      if (fileExists && ext === ".txt") {
        const content = fs.readFileSync(file_path, "utf-8").slice(0, 3000);
        await client.sendMessage(CHANNEL_ID, `${caption}\n\n─────────────\n${content}`);
      } else if (fileExists) {
        const media = MessageMedia.fromFilePath(file_path);
        await client.sendMessage(CHANNEL_ID, media, { caption });
      } else {
        await client.sendMessage(CHANNEL_ID, caption);
      }

      markAsSent(id);
      console.log(`  ✅ Sent: ${notice.title.slice(0, 60)}`);
      await new Promise((r) => setTimeout(r, 3000));

    } catch (err) {
      console.error(`  ❌ Failed: ${err.message}`);
    }
  }
  console.log("✅ All done.");
}

// ── WhatsApp Client ───────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: {
    headless: true,
    executablePath: "/usr/bin/chromium-browser",
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-extensions",
      "--single-process",
    ],
  },
});

// If QR is requested it means session failed — exit instead of hanging
client.on("qr", () => {
  console.error("❌ Session expired or invalid — QR requested. Re-run auth workflow.");
  process.exit(1);
});

client.on("ready", async () => {
  console.log("✅ WhatsApp ready!");
  await sendNotices(client);
  process.exit(0);
});

client.on("auth_failure", (msg) => {
  console.error("❌ Auth failed:", msg);
  process.exit(1);
});

client.initialize();
