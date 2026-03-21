// run_once_auth.js
// Triggered via GitHub Actions "Auth" workflow.
// Shows QR in logs → scan with WhatsApp → saves Linux session.

const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

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

client.on("qr", (qr) => {
  console.log("\n📱 Scan this QR code with WhatsApp:\n");
  qrcode.generate(qr, { small: true });
  console.log("\n⏳ You have 60 seconds to scan...\n");
});

client.on("ready", async () => {
  console.log("\n✅ Authenticated! Waiting for sync...");
  
  // Wait 30 seconds for WhatsApp to fully sync chat history
  await new Promise((r) => setTimeout(r, 30000));
  console.log("✅ Sync wait done");

  // Trigger a fake fetch to warm up the session
  try {
    const chats = await client.getChats();
    console.log(`✅ Fetched ${chats.length} chats — session is warm`);

    const channels = chats.filter(
      (c) => c.isChannel || c.id._serialized.includes("newsletter")
    );
    const groups = chats.filter((c) => c.isGroup);

    console.log("\n📢 Your Channels:");
    if (channels.length === 0) console.log("  (none found)");
    channels.forEach((c) => console.log(`  - ${c.name}: ${c.id._serialized}`));

    console.log("\n👥 Your Groups:");
    if (groups.length === 0) console.log("  (none found)");
    groups.forEach((g) => console.log(`  - ${g.name}: ${g.id._serialized}`));

  } catch (e) {
    console.log("⚠️ Fetch warning:", e.message);
  }

  process.exit(0);
});

client.on("auth_failure", (msg) => {
  console.error("❌ Auth failed:", msg);
  process.exit(1);
});

client.initialize();
