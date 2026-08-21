import discord
from utils.logger import logger

def setup(tree: discord.app_commands.CommandTree):
	"""Registers the /leave-voice-chat command on the given command tree."""

	#* /leave-voice-chat command
	@tree.command(name="leave-voice-chat", description="Stops playback and disconnects the bot from the voice channel.")
	async def stop(interaction: discord.Interaction):
		"""Stops audio playback and disconnects the bot from the voice channel."""
		logger.info(f"🕹️ @{interaction.user} used /leave-voice-chat 🕹️", extra={"channel_notify": True})
		voice_client = interaction.guild.voice_client

		# Verify the bot is actually connected before attempting to stop
		if voice_client is None:
			logger.warning(f"@{interaction.user} used /leave-voice-chat but the bot is not in a voice channel")
			await interaction.response.send_message("I am not in a voice channel.", ephemeral=True)
			return

		# Stop playback and disconnect from the voice channel
		logger.debug("Stopping playback and disconnecting from voice channel")
		voice_client.stop()
		await voice_client.disconnect()
		logger.info(f"⏸️ Disconnected from voice channel (requested by @{interaction.user}) ⏸️")
		await interaction.response.send_message("Stopped and disconnected.")