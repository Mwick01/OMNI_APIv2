// run_once_auth.js
// Run via GitHub Actions "Auth" workflow once to scan QR and save session.
// Baileys saves auth as small JSON files — no Chromium needed!

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");
const qrcode = require("qrcode-terminal");
const { Boom } = require("@hapi/boom");

async function auth() {
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
      console.log("\n📱 Scan this QR code with WhatsApp:\n");
      qrcode.generate(qr, { small: true });
      console.log("\n⏳ You have 60 seconds to scan...\n");
    }

    if (connection === "open") {
      console.log("\n✅ Authenticated! Session saved to auth_info/");
      console.log("⏳ Waiting 10s for session to stabilize...");
      await new Promise((r) => setTimeout(r, 10000));

      // Print channel/group IDs
      try {
        const groups = await sock.groupFetchAllParticipating();
        console.log("\n👥 Your Groups:");
        Object.values(groups).forEach((g) =>
          console.log(`  - ${g.subject}: ${g.id}`)
        );
      } catch (e) {
        console.log("⚠️ Could not fetch groups:", e.message);
      }

      console.log(`\n📢 Your Channel ID (set this as WHATSAPP_CHANNEL_ID secret):`);
      console.log(`   ${process.env.WHATSAPP_CHANNEL_ID || "120363XXXXXXXXXX@newsletter"}`);

      process.exit(0);
    }

    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      const reason = lastDisconnect?.error?.message || "unknown";
      console.log(`Connection closed — code: ${code}, reason: ${reason}`);

      if (code === DisconnectReason.restartRequired) {
        console.log("🔄 Restart required — retrying once...");
        auth();
      } else {
        console.error(`❌ Fatal disconnect — exiting.`);
        process.exit(1);
      }
    }
  });
}

auth();