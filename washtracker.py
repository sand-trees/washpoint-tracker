import discord
import requests
from discord.ext import commands
import json

# config docs:
# room number = str
# organisation id = str
# when is soon = int
# interval = int
#
# room number and organisation id are in the url for the status page
# https://wa.sqinsights.com/XXXXXX?room=YYYY
#                           org id     room no
# when is soon is the number of seconds a machine needs complete its
# cycle within to be considered "finishing soon"
# interval is how many seconds to wait between checks


class Machine:
    def __init__(self, status_dict):
        self.id = int(status_dict["networkNode"])
        self.type = status_dict["machineType"]["typeName"]
        self.is_a_washer = bool(status_dict["machineType"]["isWasher"])
        inner_status = json.loads(status_dict["currentStatus"])
        self.real_state = inner_status["statusId"]
        self.state = self.to_fstate()
        self.time_remaining = inner_status["remainingSeconds"]

    def __lt__(self, other):
        return self.id < other.id

    status_mappings = {
        "Available": ("AVAILABLE", "READY_TO_START"),
        "In use": ("IN_USE", "DOOR_OPEN", "LUCKY_CYCLE", "RESERVED"),
        "Complete": "COMPLETE",
        "Offline": ("ERROR", "DEFAULT", "UNKNOWN", "NETWORK_ERROR", "UNAVAILABLE")
    }

    def to_fstate(self):
        for state in self.status_mappings:
            if self.real_state in self.status_mappings[state]:
                return state
        return None

    def is_washer(self):
        return self.is_a_washer

    @staticmethod
    def format_time(seconds):
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}m {seconds}s"

    def format(self):
        base = f"ID: {self.id}\nState: {self.state} ({self.real_state})"
        if self.state == "In use":
            base += f" with {self.format_time(self.time_remaining)}"
        return base + '\n'


class Tracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        conf = self.conf = configparser.ConfigParser()
        self.conf.read("washtracker.ini")
        self.room_id = conf["room number"]
        self.org_id = conf["organisation id"]
        self.interval = int(conf["interval"])
        self.soon = int(conf["when is soon"])
        self.watching = []

    async def main(self, ctx):
        print("Checking laundry machine status")
        data = requests.get(f"https://api.alliancelslabs.com/washAlert/machines/{self.room_id}",
                            headers={"Alliancels-Organization-Id": str(self.org_id)})
        if data.status_code != 200:
            await ctx.send(f"Failed to fetch washing data: got status code {data.status_code}\n{data.content}")
        data = data.json()

        washers = []
        dryers = []
        for machine in data:
            machine = Machine(machine)
            if machine.is_washer():
                washers.append(machine)
            else:
                dryers.append(machine)
        washers.sort()
        dryers.sort()

        washers_finishing, washers_finished = await self.check_machines(ctx, washers)
        dryers_finishing, dryers_finished = await self.check_machines(ctx, dryers)
        if len(washers_finished) + len(dryers_finished) > 0:
            embed = discord.Embed(title="Available machines")
            embed.description = (f"Washers: {len(washers_finished)}\n"
                                 f"Dryers: {len(dryers_finished)}")
            await ctx.send(embed=embed)
        if len(washers_finishing) + len(dryers_finishing) > 0:
            embed = discord.Embed(title="Machines finishing soon")
            embed.description = (f"Washers: {len(washers_finishing)} "
                                 f"({', '.join([x.format_time(x.time_remaining) for x in washers_finishing])})\n"
                                 f"Dryers: {len(dryers_finishing)}"
                                 f"({', '.join([x.format_time(x.time_remaining) for x in dryers_finishing])})")
            return await ctx.send(embed=embed)

    async def check_machines(self, ctx, machines):
        machines_finished, machines_finishing = [], []
        for x in machines:
            if x.id in self.watching:
                await ctx.send(embed=discord.Embed(description=f"Watched machine #{x.id}"
                                                                   f"finishing in {x.format_time(x.time_remaining)}"))
            if x.state == "Available":
                machines_finished.append(x)
            elif x.time_remaining < self.soon:
                machines_finishing.append(x)
        return machines_finishing, machines_finished

    @commands.command()
    async def watch(self, ctx, machine_id):
        if machine_id in self.watching:
            self.watching.remove(machine_id)
            return await ctx.send(f"Stopped watching machine #{machine_id}")
        self.watching.append(machine_id)
        return await ctx.send(f"Added machine #{machine_id} to watch list")

def setup(bot):
    bot.add_cog(Tracker(bot))
