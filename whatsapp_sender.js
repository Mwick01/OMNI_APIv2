// whatsapp_sender.js
// Sends unsent notices to WhatsApp channel using Baileys (no Chromium needed)

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  downloadContentFromMessage,
} = require("@whiskeysockets/baileys");
const { Boom } = require("@hapi/boom");
const sqlite3 = require("better-sqlite3");
const path = require("path");
const fs = require("fs");

const CHANNEL_ID = process.env.WHATSAPP_CHANNEL_ID; // e.g. 120363XXXXXXXXXX@newsletter
const DB_PATH = path.join(__dirname, "database.db");

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

function getMimeType(ext) {
  const map = {
    ".pdf":  "application/pdf",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
  };
  return map[ext] || "application/octet-stream";
}

async function sendNotices(sock) {
  const unsent = getUnsentNotices();

  if (unsent.length === 0) {
    console.log("📭 No new notices to send.");
    return;
  }

  console.log(`📤 Sending ${unsent.length} notice(s) to channel...`);

  for (const notice of unsent) {
    const { id, file_path } = notice;
    const caption = buildCaption(notice);

    try {
      const ext = path.extname(file_path || "").toLowerCase();
      const fileExists = file_path && fs.existsSync(file_path);

      if (fileExists && ext === ".txt") {
        // Send text inline
        const content = fs.readFileSync(file_path, "utf-8").slice(0, 3000);
        await sock.sendMessage(CHANNEL_ID, {
          text: `${caption}\n\n─────────────\n${content}`,
        });

      } else if (fileExists && (ext === ".jpg" || ext === ".jpeg" || ext === ".png")) {
        // Send as image
        await sock.sendMessage(CHANNEL_ID, {
          image: fs.readFileSync(file_path),
          caption,
        });

      } else if (fileExists && ext === ".pdf") {
        // Send as document
        await sock.sendMessage(CHANNEL_ID, {
          document: fs.readFileSync(file_path),
          mimetype: "application/pdf",
          fileName: path.basename(file_path),
          caption,
        });

      } else if (fileExists && (ext === ".docx" || ext === ".doc")) {
        // Send as document
        await sock.sendMessage(CHANNEL_ID, {
          document: fs.readFileSync(file_path),
          mimetype: getMimeType(ext),
          fileName: path.basename(file_path),
          caption,
        });

      } else {
        // No file — send text only
        await sock.sendMessage(CHANNEL_ID, { text: caption });
      }

      markAsSent(id);
      console.log(`  ✅ Sent: ${notice.title.slice(0, 60)}`);
      await new Promise((r) => setTimeout(r, 2000));

    } catch (err) {
      console.error(`  ❌ Failed "${notice.title.slice(0, 40)}": ${err.message}`);
    }
  }

  console.log("✅ All done.");
}

async function main() {
  // Check session exists
  if (!fs.existsSync("auth_info/creds.json")) {
    console.error("❌ No session found. Run auth workflow first.");
    process.exit(1);
  }

  const { state, saveCreds } = await useMultiFileAuthState("auth_info");

  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    logger: require("pino")({ level: "silent" }),
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.error("❌ Session expired — QR requested. Re-run auth workflow.");
      process.exit(1);
    }

    if (connection === "open") {
      console.log("✅ WhatsApp connected!");
      await sendNotices(sock);
      process.exit(0);
    }

    if (connection === "close") {
      const code = (lastDisconnect?.error)?.output?.statusCode;
      console.error(`❌ Connection closed (code ${code})`);
      process.exit(1);
    }
  });
}

main();