import os
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz
from dotenv import load_dotenv
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    Message,
    Chat,
    Bot as TelegramBot,
    ParseMode
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
    CallbackContext,
    ConversationHandler
)
from telegram.error import TelegramError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = json.loads(os.getenv('ADMIN_IDS', '[]'))
DATABASE_URL = os.getenv('DATABASE_URL')

# Conversation states
(
    SELECTING_ACTION,
    TYPING_CHANNEL,
    TYPING_POST,
    SELECTING_CHANNEL,
    SELECTING_BOT,
    SETTING_TIMEZONE,
    SCHEDULING_POST,
    EDITING_POST,
    CREATING_TARIFF,
    SUBSCRIPTION_SETTINGS
) = range(10)

# Database models (simplified - in production use SQLAlchemy or similar)
class Database:
    def __init__(self):
        self.users = {}
        self.channels = {}
        self.posts = {}
        self.scheduled_posts = {}
        self.bots = {}
        self.subscriptions = {}
        
    def save_user(self, user_id: int, data: Dict):
        self.users[user_id] = data
        
    def get_user(self, user_id: int) -> Optional[Dict]:
        return self.users.get(user_id)
        
    def save_channel(self, channel_id: int, data: Dict):
        self.channels[channel_id] = data
        
    def get_channel(self, channel_id: int) -> Optional[Dict]:
        return self.channels.get(channel_id)
        
    def get_user_channels(self, user_id: int) -> List[Dict]:
        return [c for c in self.channels.values() if user_id in c.get('admins', [])]

# Initialize database
db = Database()

# Language strings (simplified version from your config)
LANG = {
    'start': """
I can help you manage Telegram channels.

You can control me by sending these commands:

/newpost - create a new post
/addchannel - add a new channel
/mychannels - edit your channels
/settings - other settings
""",
    'channels': {
        'add': """
<b>Adding a channel</b>

To add a channel you should follow these two steps:

1. Add the bot to admins of your channel.
2. Then forward to me any message from your channel (you can also send me its username or ID).
""",
        'added': "Success! The channel has been added."
    }
}

class TelegramChannelBot:
    def __init__(self, token: str):
        self.updater = Updater(token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.bot = self.updater.bot
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup all command and message handlers"""
        
        # Command handlers
        self.dispatcher.add_handler(CommandHandler('start', self.start))
        self.dispatcher.add_handler(CommandHandler('help', self.help_command))
        self.dispatcher.add_handler(CommandHandler('newpost', self.new_post))
        self.dispatcher.add_handler(CommandHandler('addchannel', self.add_channel))
        self.dispatcher.add_handler(CommandHandler('mychannels', self.my_channels))
        self.dispatcher.add_handler(CommandHandler('settings', self.settings))
        self.dispatcher.add_handler(CommandHandler('lang', self.change_language))
        
        # Message handlers
        self.dispatcher.add_handler(MessageHandler(
            Filters.forwarded, 
            self.handle_forwarded_message
        ))
        
        self.dispatcher.add_handler(MessageHandler(
            Filters.text & ~Filters.command,
            self.handle_text_message
        ))
        
        # Callback query handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Error handler
        self.dispatcher.add_error_handler(self.error_handler)
        
    def start(self, update: Update, context: CallbackContext):
        """Send welcome message when command /start is issued."""
        user = update.effective_user
        
        # Initialize user data
        user_data = db.get_user(user.id) or {}
        user_data['id'] = user.id
        user_data['username'] = user.username
        user_data['first_name'] = user.first_name
        user_data['language'] = user_data.get('language', 'en')
        db.save_user(user.id, user_data)
        
        # Send welcome message with preserved formatting
        update.message.reply_text(
            LANG['start'],
            parse_mode=ParseMode.HTML,
            reply_markup=self.get_main_menu_keyboard()
        )
        
        return SELECTING_ACTION
        
    def help_command(self, update: Update, context: CallbackContext):
        """Send help message."""
        help_text = """
<b>Controller Bot Help</b>

I can help you manage Telegram channels with these features:

📝 <b>Create Posts</b> - Create formatted posts with markdown/HTML
🔄 <b>Edit Posts</b> - Edit existing posts in your channels
⏰ <b>Schedule Posts</b> - Schedule posts for later delivery
📊 <b>View Statistics</b> - Get channel analytics
💰 <b>Paid Subscriptions</b> - Manage paid channel subscriptions
⚙️ <b>Channel Management</b> - Add/remove channels and bots

<b>Available Commands:</b>
/start - Main menu
/newpost - Create new post
/addchannel - Add new channel
/mychannels - Manage your channels
/settings - Bot settings
/lang - Change language

For detailed help, visit our <a href="https://telegra.ph/Controller-Help-03-20">Help Page</a>
        """
        
        update.message.reply_text(
            help_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )
        
    def new_post(self, update: Update, context: CallbackContext):
        """Start creating a new post."""
        user = update.effective_user
        user_channels = db.get_user_channels(user.id)
        
        if not user_channels:
            update.message.reply_text(
                "There is no added channels yet.\n\nSend /addchannel to add a new one.",
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END
            
        # Show channel selection
        keyboard = []
        for channel in user_channels:
            channel_name = channel.get('name', 'Unknown Channel')
            if channel.get('username'):
                channel_name += f" (@{channel['username']})"
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 {channel_name}",
                    callback_data=f"select_channel_{channel['id']}"
                )
            ])
            
        keyboard.append([
            InlineKeyboardButton("« Back", callback_data="back_to_main")
        ])
        
        update.message.reply_text(
            "Choose a channel to create a new post:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
        return SELECTING_CHANNEL
        
    def add_channel(self, update: Update, context: CallbackContext):
        """Start adding a new channel."""
        update.message.reply_text(
            LANG['channels']['add'],
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="back_to_main")]
            ])
        )
        
        return TYPING_CHANNEL
        
    def my_channels(self, update: Update, context: CallbackContext):
        """Show user's channels."""
        user = update.effective_user
        user_channels = db.get_user_channels(user.id)
        
        if not user_channels:
            update.message.reply_text(
                "You don't have any channels yet. Use /addchannel to add one.",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Create channel list with management options
        keyboard = []
        for channel in user_channels:
            channel_name = channel.get('name', 'Unknown')
            channel_id = channel['id']
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📢 {channel_name}",
                    callback_data=f"manage_channel_{channel_id}"
                )
            ])
            
        keyboard.append([
            InlineKeyboardButton("« Back", callback_data="back_to_main")
        ])
        
        update.message.reply_text(
            f"📋 <b>Your Channels</b>\n\nYou have {len(user_channels)} channel(s). Select one to manage:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
    def settings(self, update: Update, context: CallbackContext):
        """Show settings menu."""
        keyboard = [
            [InlineKeyboardButton("🌐 Change Language", callback_data="change_language")],
            [InlineKeyboardButton("🤖 Manage Bots", callback_data="manage_bots")],
            [InlineKeyboardButton("⚙️ Post Settings", callback_data="post_settings")],
            [InlineKeyboardButton("« Back", callback_data="back_to_main")]
        ]
        
        update.message.reply_text(
            "⚙️ <b>Settings</b>\n\nChoose what you want to change:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
    def change_language(self, update: Update, context: CallbackContext):
        """Change bot language."""
        keyboard = [
            [
                InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
                InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")
            ],
            [InlineKeyboardButton("« Back", callback_data="back_to_main")]
        ]
        
        update.message.reply_text(
            "Please choose your language:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    def handle_forwarded_message(self, update: Update, context: CallbackContext):
        """Handle forwarded messages for channel addition."""
        message = update.message
        user = update.effective_user
        
        # Check if we're in channel adding mode
        if not context.user_data.get('adding_channel'):
            return
            
        # Extract channel info from forwarded message
        if message.forward_from_chat and message.forward_from_chat.type in ['channel', 'group']:
            chat = message.forward_from_chat
            
            # Check if user is admin in the channel
            try:
                chat_member = context.bot.get_chat_member(chat.id, user.id)
                if chat_member.status not in ['creator', 'administrator']:
                    update.message.reply_text(
                        "You aren't an administrator in this channel.",
                        parse_mode=ParseMode.HTML
                    )
                    return
            except TelegramError:
                update.message.reply_text(
                    "Unable to verify your admin status. Please make sure the bot is added as admin.",
                    parse_mode=ParseMode.HTML
                )
                return
                
            # Save channel to database
            channel_data = {
                'id': chat.id,
                'name': chat.title,
                'username': chat.username,
                'type': chat.type,
                'admins': [user.id],
                'owner_id': user.id,
                'added_date': datetime.now().isoformat(),
                'bot_token': None,
                'timezone': 'UTC'
            }
            
            db.save_channel(chat.id, channel_data)
            
            # Send success message
            success_msg = f"""
✅ <b>Channel Added Successfully!</b>

<b>Channel:</b> {chat.title}
<b>Username:</b> @{chat.username if chat.username else 'Private'}
<b>Type:</b> {chat.type.capitalize()}

Now you can:
1. Go to @{context.bot.username} to create posts
2. Add more admins in channel settings
3. Set up timezone for scheduling

<code>/newpost</code> - Create your first post
<code>/mychannels</code> - Manage your channels
            """
            
            update.message.reply_text(
                success_msg,
                parse_mode=ParseMode.HTML,
                reply_markup=self.get_main_menu_keyboard()
            )
            
            # Clear adding channel state
            context.user_data.pop('adding_channel', None)
            
    def handle_text_message(self, update: Update, context: CallbackContext):
        """Handle text messages for post creation."""
        message = update.message
        user = update.effective_user
        
        # Check if we're in post creation mode
        if context.user_data.get('creating_post'):
            channel_id = context.user_data.get('selected_channel')
            channel = db.get_channel(channel_id)
            
            if not channel:
                update.message.reply_text("Channel not found.")
                return
                
            # Store the message for the post
            if 'post_messages' not in context.user_data:
                context.user_data['post_messages'] = []
                
            # Preserve all formatting
            message_data = {
                'text': message.text_html if message.text_html else message.text_markdown,
                'parse_mode': 'HTML' if message.text_html else 'Markdown',
                'entities': message.entities,
                'message_id': message.message_id,
                'date': datetime.now().isoformat()
            }
            
            # Check for media
            if message.photo:
                message_data['photo'] = message.photo[-1].file_id
                message_data['caption'] = message.caption_html if message.caption_html else message.caption
                message_data['caption_entities'] = message.caption_entities
            elif message.video:
                message_data['video'] = message.video.file_id
                message_data['caption'] = message.caption_html if message.caption_html else message.caption
                message_data['caption_entities'] = message.caption_entities
            elif message.document:
                message_data['document'] = message.document.file_id
                message_data['caption'] = message.caption_html if message.caption_html else message.caption
                message_data['caption_entities'] = message.caption_entities
                
            context.user_data['post_messages'].append(message_data)
            
            # Show post preview
            self.show_post_preview(update, context)
            
    def handle_callback(self, update: Update, context: CallbackContext):
        """Handle inline keyboard callbacks."""
        query = update.callback_query
        user = update.effective_user
        
        # Answer callback query
        query.answer()
        
        data = query.data
        
        if data == 'back_to_main':
            self.show_main_menu(query)
            
        elif data.startswith('select_channel_'):
            channel_id = int(data.split('_')[-1])
            context.user_data['selected_channel'] = channel_id
            context.user_data['creating_post'] = True
            
            channel = db.get_channel(channel_id)
            if channel:
                query.edit_message_text(
                    f"📝 <b>Creating post for:</b> {channel['name']}\n\n"
                    "Send me the content for your post. You can send:\n"
                    "• Text with formatting\n"
                    "• Photos with captions\n"
                    "• Videos with captions\n"
                    "• Documents\n\n"
                    "When finished, click 'Preview' below.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self.get_post_creation_keyboard()
                )
                
        elif data == 'post_preview':
            self.show_post_preview(update, context, is_callback=True)
            
        elif data == 'send_post':
            self.send_post_to_channel(update, context)
            
        elif data == 'schedule_post':
            self.schedule_post(update, context)
            
        elif data.startswith('lang_'):
            lang = data.split('_')[1]
            user_data = db.get_user(user.id) or {}
            user_data['language'] = lang
            db.save_user(user.id, user_data)
            
            query.edit_message_text(
                f"Language changed to {'English' if lang == 'en' else 'Russian'}.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="back_to_main")]
                ])
            )
            
    def show_main_menu(self, query):
        """Show main menu."""
        query.edit_message_text(
            LANG['start'],
            parse_mode=ParseMode.HTML,
            reply_markup=self.get_main_menu_keyboard()
        )
        
    def get_main_menu_keyboard(self):
        """Get main menu inline keyboard."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Create Post", callback_data="create_post")],
            [InlineKeyboardButton("📢 My Channels", callback_data="my_channels")],
            [InlineKeyboardButton("⏰ Scheduled Posts", callback_data="scheduled_posts")],
            [InlineKeyboardButton("📊 Statistics", callback_data="statistics")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("❓ Help", callback_data="help")]
        ])
        
    def get_post_creation_keyboard(self):
        """Get keyboard for post creation."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📎 Add Media", callback_data="add_media"),
                InlineKeyboardButton("🔗 Add Buttons", callback_data="add_buttons")
            ],
            [
                InlineKeyboardButton("👀 Preview", callback_data="post_preview"),
                InlineKeyboardButton("🗑 Clear All", callback_data="clear_post")
            ],
            [
                InlineKeyboardButton("⏰ Schedule", callback_data="schedule_post"),
                InlineKeyboardButton("📤 Send Now", callback_data="send_post")
            ],
            [InlineKeyboardButton("« Cancel", callback_data="back_to_main")]
        ])
        
    def show_post_preview(self, update: Update, context: CallbackContext, is_callback=False):
        """Show preview of the post being created."""
        post_messages = context.user_data.get('post_messages', [])
        channel_id = context.user_data.get('selected_channel')
        channel = db.get_channel(channel_id) if channel_id else None
        
        if not post_messages:
            text = "No content added yet. Send me messages to build your post."
            keyboard = self.get_post_creation_keyboard()
        else:
            # Build preview text
            preview_text = f"📋 <b>Post Preview</b>\n\n"
            preview_text += f"<b>Channel:</b> {channel['name'] if channel else 'Not selected'}\n"
            preview_text += f"<b>Messages:</b> {len(post_messages)}\n\n"
            
            # Show first 3 messages as preview
            for i, msg in enumerate(post_messages[:3], 1):
                if msg.get('text'):
                    text_preview = msg['text'][:100] + "..." if len(msg['text']) > 100 else msg['text']
                    preview_text += f"{i}. 📝 {text_preview}\n"
                elif msg.get('photo'):
                    preview_text += f"{i}. 📷 Photo with caption\n"
                elif msg.get('video'):
                    preview_text += f"{i}. 🎥 Video with caption\n"
                elif msg.get('document'):
                    preview_text += f"{i}. 📄 Document with caption\n"
                    
            if len(post_messages) > 3:
                preview_text += f"\n... and {len(post_messages) - 3} more messages"
                
            text = preview_text
            keyboard = self.get_post_creation_keyboard()
            
        if is_callback:
            update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
            
    def send_post_to_channel(self, update: Update, context: CallbackContext):
        """Send post to selected channel."""
        query = update.callback_query
        channel_id = context.user_data.get('selected_channel')
        channel = db.get_channel(channel_id)
        post_messages = context.user_data.get('post_messages', [])
        
        if not channel:
            query.answer("Channel not found.", show_alert=True)
            return
            
        if not post_messages:
            query.answer("No content to send.", show_alert=True)
            return
            
        try:
            # Get bot token for this channel
            bot_token = channel.get('bot_token')
            if not bot_token:
                query.answer(
                    "No bot connected to this channel. Please add a bot first.",
                    show_alert=True
                )
                return
                
            # Create bot instance
            channel_bot = TelegramBot(token=bot_token)
            
            # Send messages to channel with preserved formatting
            sent_messages = []
            for msg_data in post_messages:
                if msg_data.get('photo'):
                    sent_msg = channel_bot.send_photo(
                        chat_id=channel_id,
                        photo=msg_data['photo'],
                        caption=msg_data.get('caption', ''),
                        parse_mode=ParseMode.HTML,
                        caption_entities=msg_data.get('caption_entities')
                    )
                elif msg_data.get('video'):
                    sent_msg = channel_bot.send_video(
                        chat_id=channel_id,
                        video=msg_data['video'],
                        caption=msg_data.get('caption', ''),
                        parse_mode=ParseMode.HTML,
                        caption_entities=msg_data.get('caption_entities')
                    )
                elif msg_data.get('text'):
                    sent_msg = channel_bot.send_message(
                        chat_id=channel_id,
                        text=msg_data['text'],
                        parse_mode=ParseMode.HTML,
                        entities=msg_data.get('entities')
                    )
                else:
                    continue
                    
                sent_messages.append(sent_msg.message_id)
                
            # Store post data
            post_id = f"{channel_id}_{datetime.now().timestamp()}"
            post_data = {
                'id': post_id,
                'channel_id': channel_id,
                'user_id': update.effective_user.id,
                'messages': post_messages,
                'sent_messages': sent_messages,
                'sent_date': datetime.now().isoformat(),
                'type': 'instant'
            }
            
            db.posts[post_id] = post_data
            
            # Send success message with reply functionality
            success_text = f"""
✅ <b>Post Successfully Sent!</b>

<b>Channel:</b> {channel['name']}
<b>Messages:</b> {len(sent_messages)}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

You can now reply to this post directly in the channel.
            """
            
            # Create reply keyboard
            reply_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👁 View in Channel",
                        url=f"https://t.me/c/{str(channel_id)[4:]}/{sent_messages[0]}" if sent_messages else "#"
                    )
                ],
                [InlineKeyboardButton("📝 New Post", callback_data="create_post")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
            ])
            
            query.edit_message_text(
                success_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_keyboard
            )
            
            # Clear post data
            context.user_data.pop('post_messages', None)
            context.user_data.pop('selected_channel', None)
            context.user_data.pop('creating_post', None)
            
        except TelegramError as e:
            logger.error(f"Error sending post: {e}")
            query.answer(f"Error sending post: {str(e)}", show_alert=True)
            
    def schedule_post(self, update: Update, context: CallbackContext):
        """Schedule a post for later delivery."""
        query = update.callback_query
        
        # Ask for schedule time
        query.edit_message_text(
            "⏰ <b>Schedule Post</b>\n\n"
            "Send the time when you want to send this post.\n"
            "Format: <code>HH:MM</code> or <code>HH:MM DD.MM.YYYY</code>\n\n"
            "Examples:\n"
            "• <code>14:30</code> - Today at 2:30 PM\n"
            "• <code>09:00 25.12.2023</code> - Dec 25, 2023 at 9:00 AM\n\n"
            "Or choose one of the quick options below:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Today 09:00", callback_data="schedule_today_0900"),
                    InlineKeyboardButton("Today 18:00", callback_data="schedule_today_1800")
                ],
                [
                    InlineKeyboardButton("Tomorrow 09:00", callback_data="schedule_tomorrow_0900"),
                    InlineKeyboardButton("Tomorrow 18:00", callback_data="schedule_tomorrow_1800")
                ],
                [InlineKeyboardButton("« Back", callback_data="post_preview")]
            ])
        )
        
        context.user_data['scheduling_post'] = True
        return SCHEDULING_POST
        
    def error_handler(self, update: Update, context: CallbackContext):
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")
        
        # Try to notify user about error
        try:
            if update and update.effective_message:
                update.effective_message.reply_text(
                    "❌ An error occurred. Please try again.\n\n"
                    "If the problem persists, contact @ControllerSupportBot",
                    parse_mode=ParseMode.HTML
                )
        except:
            pass

class ReplyManager:
    """Manager for handling replies to channel posts."""
    
    @staticmethod
    def create_reply_keyboard(channel_id: int, message_id: int):
        """Create inline keyboard for replying to a post."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 Reply",
                    callback_data=f"reply_{channel_id}_{message_id}"
                ),
                InlineKeyboardButton(
                    "🔄 Forward",
                    callback_data=f"forward_{channel_id}_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Stats",
                    callback_data=f"stats_{channel_id}_{message_id}"
                ),
                InlineKeyboardButton(
                    "✏️ Edit",
                    callback_data=f"edit_{channel_id}_{message_id}"
                )
            ]
        ])
        
    @staticmethod
    def handle_reply(update: Update, context: CallbackContext, channel_id: int, message_id: int):
        """Handle reply to a channel post."""
        query = update.callback_query
        user = update.effective_user
        
        # Store reply context
        context.user_data['replying_to'] = {
            'channel_id': channel_id,
            'message_id': message_id,
            'user_id': user.id
        }
        
        query.edit_message_text(
            "💬 <b>Reply to Post</b>\n\n"
            "Send your reply message. It will be posted as a comment/reply in the channel.\n\n"
            "You can send text, photos, videos, or any other media.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Cancel", callback_data="cancel_reply")]
            ])
        )
        
    @staticmethod
    def send_reply(context: CallbackContext, reply_data: Dict, original_message_id: int):
        """Send reply to a channel post."""
        try:
            channel_id = reply_data['channel_id']
            user_id = reply_data['user_id']
            message_text = reply_data.get('text', '')
            media = reply_data.get('media')
            
            # Get channel and bot
            channel = db.get_channel(channel_id)
            if not channel or not channel.get('bot_token'):
                return False
                
            bot = TelegramBot(token=channel['bot_token'])
            
            # Send reply as a comment/reply to original message
            if media:
                # Handle media reply
                if media.get('photo'):
                    bot.send_photo(
                        chat_id=channel_id,
                        photo=media['photo'],
                        caption=message_text,
                        reply_to_message_id=original_message_id,
                        parse_mode=ParseMode.HTML
                    )
                elif media.get('video'):
                    bot.send_video(
                        chat_id=channel_id,
                        video=media['video'],
                        caption=message_text,
                        reply_to_message_id=original_message_id,
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Text-only reply
                bot.send_message(
                    chat_id=channel_id,
                    text=message_text,
                    reply_to_message_id=original_message_id,
                    parse_mode=ParseMode.HTML
                )
                
            return True
            
        except Exception as e:
            logger.error(f"Error sending reply: {e}")
            return False

# Main function
def main():
    """Start the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is required")
        
    # Create and start bot
    bot = TelegramChannelBot(BOT_TOKEN)
    
    # Start the Bot
    bot.updater.start_polling()
    bot.updater.idle()

if __name__ == '__main__':
    main()
