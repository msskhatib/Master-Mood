# ElevenLabs Page Reader (Chrome extension)

This extension reads text on any web page aloud in Google Chrome, using your ElevenLabs voices.

## Install (2 minutes)
1. Download this folder (`elevenlabs-chrome-reader`) to your computer.
2. In Chrome, open `chrome://extensions`.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and pick the `elevenlabs-chrome-reader` folder.
5. The Settings page opens. Paste your ElevenLabs API key, click **Load my voices**, choose a voice, then click **Save** and **Test voice**.

> Your key is saved only in your Chrome profile (`chrome.storage`). Never put it in code or share it.
> In ElevenLabs, the key needs the **Text to Speech** permission. To use **Load my voices**, it also needs **Voices: read**.

## How to use
| Action | How |
|---|---|
| Read a sentence | Select text, then right-click and choose **Read with ElevenLabs**, or press **Alt+Shift+R** |
| Read the whole page | Right-click an empty part of the page and choose **Read whole page with ElevenLabs**, or use the popup |
| Read typed text | Click the toolbar icon, paste the text, then click **Read this text** |
| Pause, resume or stop | Use the popup buttons, or press **Alt+Shift+S** to stop |

To change the shortcuts, go to `chrome://extensions/shortcuts`.

## How it works
- `background.js` gets the selected text or the main text of the page. It splits the text into sentence groups of 2,500 characters or fewer. It calls `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` with the `xi-api-key` header. It fetches the next group while the current one plays.
- `offscreen.js` plays the MP3 audio in order. Chrome MV3 service workers cannot play sound, so playback happens in this separate page.
- Models: **Multilingual v2** is the default and handles Arabic and English. **Flash v2.5** is the fastest and uses fewer credits.

Every character you read uses ElevenLabs credits.
