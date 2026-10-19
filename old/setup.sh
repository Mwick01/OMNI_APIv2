#!/bin/bash
# Run this once on your GCP VM to set everything up

set -e

echo "📦 Installing dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv git

echo "📁 Setting up project..."
cd ~ 
# Removes existing folder if it exists so the script doesn't crash on re-runs
rm -rf notice-bot 
git clone https://github.com/Mwick01/OMNI_APIv2.git notice-bot
cd notice-bot

echo "🐍 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "📝 Creating .env file..."
cat > .env << 'ENVEOF'
SITE_USERNAME=your_username
SITE_PASSWORD=your_password
LOGIN_URL=your_login_url
NOTICE_URL=your_notice_url
GREEN_API_INSTANCE=your_instance
GREEN_API_TOKEN=your_token
WHATSAPP_GROUP_ID=your_group_id
ENVEOF

echo "⏰ Setting up cron jobs..."
(crontab -l 2>/dev/null; cat << CRONEOF

# RUH Notice Bot - Smart Schedule (Sri Lanka Time UTC+5:30)

# Weekdays peak hours 8AM-5PM SL (2:30AM-11:30AM UTC) - every 5 mins
*/5 3-11 * * 1-5 cd $HOME/notice-bot && $HOME/notice-bot/venv/bin/python3 main.py >> $HOME/cron.log 2>&1
30 2 * * 1-5 cd $HOME/notice-bot && $HOME/notice-bot/venv/bin/python3 main.py >> $HOME/cron.log 2>&1

# Weekdays off hours (every 20 mins)
*/20 0-2 * * 1-5 cd $HOME/notice-bot && $HOME/notice-bot/venv/bin/python3 main.py >> $HOME/cron.log 2>&1
*/20 12-23 * * 1-5 cd $HOME/notice-bot && $HOME/notice-bot/venv/bin/python3 main.py >> $HOME/cron.log 2>&1

# Weekends all day (every 20 mins)
*/20 * * * 6,0 cd $HOME/notice-bot && $HOME/notice-bot/venv/bin/python3 main.py >> $HOME/cron.log 2>&1
CRONEOF
) | crontab -

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your actual credentials: nano $HOME/notice-bot/.env"
echo "2. Run manually: cd $HOME/notice-bot && source venv/bin/activate && python3 main.py"
echo "3. Check cron logs: tail -f $HOME/cron.log"