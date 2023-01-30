from owcv import ComputerVision


class OverwatchStateTracker:
	def __init__(self, final_resolution):
		coords = {
			"elimination":[749, 850, 832, 976],
			"assist":[749, 850, 832, 976],
			"saved":[749, 850, 727, 922],
			"killcam":[89, 107, 41, 69],
			"death_spec":[66, 86, 1416, 1574],
			"heal_beam":[650, 730, 790, 860],
			"damage_beam":[658, 719, 1065, 1126],
			"resurrect_cd":[920, 1000, 1580, 1655],
			"being_beamed":[762, 807, 460, 508],
			}
		to_mask = [
			"heal_beam",
			"damage_beam",
			]
		self.owcv = ComputerVision(coords, to_mask, final_resolution)
		self.hero = "Other"
		self.in_killcam = False
		self.death_spectating = False
		self.is_dead = False
		self.elim_notifs = 0
		self.assist_notifs = 0
		self.saved_notifs = 0
		self.being_beamed = False
		self.heal_beam = False
		self.damage_beam = False
		self.resurrecting = False
		self.heal_beam_active_confs = 0
		self.damage_beam_active_confs = 0
		self.pos_required_confs = 1
		self.neg_required_confs = 8

	def refresh(self, capture_frame_only=False):
		self.owcv.capture_frame()
		if capture_frame_only:
			return

		# Find out if the player is alive
		self.in_killcam = self.owcv.detect_single("killcam")
		if not self.in_killcam:
			self.death_spectating = self.owcv.detect_single("death_spec")
		player_is_alive = not (self.in_killcam or self.death_spectating)
		
		if player_is_alive:
			self.elim_notifs = self.owcv.detect_multiple("elimination")
			self.assist_notifs = self.owcv.detect_multiple("assist")
			self.saved_notifs = self.owcv.detect_multiple("saved")
			self.being_beamed = self.owcv.detect_single("being_beamed")
			if self.hero == "Mercy":
				self.detect_mercy_beams()
				if self.saved_notifs > 0:
					self.resurrecting = self.owcv.detect_single("resurrect_cd")
		else:
			if not self.is_dead:
				self.is_dead = True
				self.elim_notifs = 0
				self.assist_notifs = 0
				self.saved_notifs = 0
				self.being_beamed = False
				if self.hero == "Mercy":
					self.heal_beam = False
					self.damage_beam = False
					self.resurrecting = False

	def detect_mercy_beams(self):
		if self.owcv.detect_single("heal_beam"):
			if self.heal_beam_active_confs == self.pos_required_confs:
				if not self.heal_beam:
					self.heal_beam = True
					self.damage_beam = False
			else:
				if self.heal_beam_active_confs <= 0:
					self.heal_beam_active_confs = 1
				else:
					self.heal_beam_active_confs += 1
		else:
			if self.heal_beam_active_confs == (0 - self.neg_required_confs):
				if self.heal_beam:
					self.heal_beam = False
			else:
				if self.heal_beam_active_confs >= 0:
					self.heal_beam_active_confs = -1
				else:
					self.heal_beam_active_confs -= 1

		if self.owcv.detect_single("damage_beam"):
			if self.damage_beam_active_confs == self.pos_required_confs:
				if not self.damage_beam:
					self.damage_beam = True
					self.heal_beam = False
			else:
				if self.damage_beam_active_confs <= 0:
					self.damage_beam_active_confs = 1
				else:
					self.damage_beam_active_confs += 1
		else:
			if self.damage_beam_active_confs == (0 - self.neg_required_confs):
				if self.damage_beam:
					self.damage_beam = False
			else:
				if self.damage_beam_active_confs >= 0:
					self.damage_beam_active_confs = -1
				else:
					self.damage_beam_active_confs -= 1

	def start_tracking(self, refresh_rate):
		self.owcv.start_capturing(refresh_rate)

	def stop_tracking(self):
		self.owcv.stop_capturing()
