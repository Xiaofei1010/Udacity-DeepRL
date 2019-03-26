# -*- coding: utf-8 -*-
import sys
import numpy as np
import time
from utils import print_bracketing, check_dir
from argparse import ArgumentParser
import torch
import os.path
import re
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from collections import deque

class Saver():
    """
    Handles the saving of checkpoints and collection of data to do so. Generates
    the savename and directory for each Agent session.
    PARAMS:
    prefix - usually the name of the framework of the agent being trained, but
            could be manually provided if desired.
    agent - agent to either load or save data to/from.
    save_dir - this will usually come from a cmdline parser
    load_file - filename of saved weights to load into the current agent.
    file_ext - extension to append to saved weights files. Can be any arbitrary
            string the user desires.
    """
    def __init__(self,
                 multi_agent,
                 args,
                 file_ext = ".agent"
                 ):
        """
        Initialize a Saver object.
        """
        load_file = self._get_agent_file(args, multi_agent.agent_count)

        self.file_ext = file_ext
        self.save_dir, self.filename = self.generate_savename(multi_agent.framework,
                                                              args.save_dir)

        if load_file:
            self._load_agent(load_file, multi_agent)
        else:
            statement = "Saving to base filename: {}".format(self.filename)
            print_bracketing(statement)


    def _get_agent_file(self, args, agent_count):
        """
        Checks to see what sort of loading, if any, to do.
        Returns one of:
            -FILENAME... if flagged with a specific filename on the cmdline
            -LASTEST FILE... if flagged to load the most recently saved weights
            -USER FILE... a user selected file from a list prompt
            -FALSE... if no loading is needed, return false and skip loading
        """

        # invalid_filename = "Requested filename is invalid."
        no_files_found = "Could not find any files in: {}".format(args.save_dir)
        if args.resume or args.eval:
            ### DEBUG: temporarily removed user-provided filepath, because it
            ### presents problems with multi-agent loading, needs further dev
            # if args.filename is not None:
            #     assert os.path.isfile(args.filename), invalid_filename
            #     return args.filename
            files = self._get_files(args.save_dir)
            assert len(files) > 0, no_files_found
            return [self._get_filepath(files, i) for i in range(agent_count)]
            ### DEBUG: temporarily removing --latest flag until further dev on
            ### multi-agent save/loads
            # if args.latest:
            #     return files[-1]
            # else:
            #     return self._get_filepath(files)
        else:
            return False

    def _get_files(self, save_dir):
        """
        Returns a list of files in a given directory, sorted by last-modified.
        """

        file_list = []
        for root, _, files in os.walk(save_dir):
            for file in files:
                if file.endswith(".agent"):
                    file_list.append(os.path.join(root, file))
        return sorted(file_list, key=lambda x: os.path.getmtime(x))

    def _get_filepath(self, files, idx):
        """
        Prompts the user about what save to load, or uses the last modified save.
        """

        load_file_prompt = "Load file for Agent #{} (or: q/quit): ".format(idx+1)
        user_quit_message = "User quit process before loading a file."
        message = ["{}. {}".format(len(files)-i, file) for i, file in enumerate(files)]
        message = '\n'.join(message).replace('\\', '/')
        message = message +  "(LATEST)\n\n" + load_file_prompt
        save_file = input(message)
        if save_file.lower() in ("q", "quit"):
            raise KeyboardInterrupt(user_quit_message)
        try:
            file_index = len(files) - int(save_file)
            assert file_index >= 0
            return files[file_index]
        except:
            print_bracketing('Input "{}" is INVALID...'.format(save_file))
            return _get_filepath(files)

    def generate_savename(self, prefix, save_dir):
        """
        Gener.ates an automatic savename for training files, will version-up as
        needed.
        """
        check_dir(save_dir)
        timestamp = time.strftime("%Y%m%d", time.localtime())
        base_name = "{}_{}_v".format(prefix, timestamp)
        files = [f for f in os.listdir(save_dir)]
        files = [f for f in files if base_name in f]
        if len(files)>0:
            ver = [int(re.search("_v(\d+)", file).group(1)) for file in files]
            ver = max(ver) + 1
        else:
            ver = 1
        filename =  "{}{:03d}".format(base_name, ver)
        save_dir = os.path.join(save_dir, filename)
        return save_dir, filename

    def save_checkpoint(self, agent, save_every):
        """
        Preps a checkpoint save file at intervals controlled by SAVE_EVERY.
        """
        if not agent.episode % save_every == 0:
            return
        mssg = "Saving Agent checkpoint to: "
        save_name = "{}_eps{:04d}_ckpt".format(self.filename, agent.episode)
        self._save(agent, save_name, mssg)

    def save_final(self, agent):
        """
        Preps a final savefile after training has finished.
        """
        mssg = "Saved final Agent weights to: "
        save_name = "{}_eps{:04d}_FINAL".format(self.filename, agent.episode-1)
        self._save(agent, save_name, mssg)

    def _save(self, multi_agent, save_name, mssg):
        """
        Does the actual saving bit.
        """

        basename = os.path.join(self.save_dir, save_name).replace('\\','/')
        statement = mssg + basename + "..."
        print("{0}\n{1}\n{0}".format("#"*len(statement), statement))
        check_dir(self.save_dir)
        for idx, agent in enumerate(multi_agent.agents):
            suffix =  "_agent{}".format(idx+1) + self.file_ext
            torch.save(self._get_save_dict(agent), basename + suffix)

    def _get_save_dict(self, agent):
        """
        Prep a dictionary of data from the current Agent.
        """

        checkpoint = {'actor_dict': agent.actor.state_dict(),
                      'critic_dict': agent.critic.state_dict()
                      }
        return checkpoint

    def _load_agent(self, load_file, multi_agent):
        """
        Loads a checkpoint from an earlier trained agent.
        """
        for idx, agent in enumerate(multi_agent.agents):
            checkpoint = torch.load(load_file[idx], map_location=lambda storage, loc: storage)
            agent.actor.load_state_dict(checkpoint['actor_dict'])
            agent.critic.load_state_dict(checkpoint['critic_dict'])
            multi_agent.update_networks(agent, force_hard=True)
        statement = ["Successfully loaded files:"]
        statement.extend(load_file)
        print_bracketing(statement)


class Logger:
    """
    Handles logging training data and printing to log files. Creates a graph at
    the end of training to compare data in a nice format. Log files are stored
    so the data can also be used elsewhere as needed. Initializing a blank
    Logger object allows to manually provide a log directory from which to parse
    data and construct a graph. This is very useful if training is still running
    but one wants to utilize a Jupyter Notebook to monitor current results.
    PARAMS:
    agent - Logger collects the params of both ARGS and AGENT in order to log
        the training session details.
    args - Logger collects the params of both ARGS and AGENT in order to log
        the training session details.
    save_dir - directory where current session saves are being stored. Logger
        will create a /logs/ directory here for storing data.
    log_every - how many timesteps between each logging of losses. Scores are
        logged every episode.
    """
    def __init__(self,
                 multi_agent=None,
                 args=None,
                 save_dir = '.',
                 ):
        """
        Initialize a Logger object.
        """
        self.save_dir = save_dir
        self.lossfiles = {}
        if multi_agent==None or args==None:
            print("Blank init for Logger object. Most functionality limited.")
            return
        self.eval = args.eval
        self.max_eps = args.num_episodes
        self.quietmode = args.quiet
        self.log_every = args.log_every # timesteps
        self.print_every = args.print_every # episodes

        self.framework =  multi_agent.framework
        self.agent_count =  multi_agent.agent_count
        self.log_dir = os.path.join(self.save_dir, 'logs').replace('\\','/')
        self.filename = os.path.basename(self.save_dir)
        self.logs_basename = os.path.join(self.log_dir, self.filename)
        self.start_time = self.prev_timestamp =  time.time()
        self.scores = deque(maxlen=self.print_every)
        self._reset_rewards()

        if not self.eval:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            statement = "Starting training at: {}".format(timestamp)
            print_bracketing(statement)

            check_dir(self.log_dir)
            params = self._collect_params(args,  multi_agent)
            self._init_logs(params, multi_agent)

    @property
    def latest_score(self):
        return self.scores[-1]

    def log(self, rewards, multi_agent=None):
        """
        After each timestep, keep track of loss and reward data.
        """

        self.rewards += rewards
        if self.eval:
            return

        # Writes the loss data to an on-disk logfile every LOG_EVERY timesteps
        if multi_agent.t_step % self.log_every == 0:
            self._write_losses(multi_agent)

    def step(self, eps_num=None, multi_agent=None):
        """
        After each episode, report data on runtime and score. If not in
        QUIETMODE, then also report the most recent losses.
        """

        self._update_score()
        self._reset_rewards()

        if self.eval:
            print("Score: {}".format(self.latest_score))
            return

        self._write_scores()

        if eps_num % self.print_every == 0 or eps_num == self.max_eps:
            eps_time, total_time, remaining = self._runtime(eps_num)
            print("\nEpisode {}/{}... Runtime: {}, Total: {}, Est.Remaining: {}\
                  ".format(eps_num, self.max_eps, eps_time, total_time, remaining))
            if not self.quietmode:
                print("Timesteps: {}".format(multi_agent.t_step))
                for idx, agent in enumerate(multi_agent.agents):
                    print("Agent {}... actorloss: {:5f}, criticloss: {:5f}\
                          ".format(idx, agent.actor_loss, agent.critic_loss))
            print("{}Avg return over previous {} episodes: {:5f}\n\
                  ".format("."*3, len(self.scores), np.array(self.scores).mean()))

    def _update_score(self):
        """
        Calculates the average reward for the previous episode, prints to the
        cmdline, and then saves to the logfile.
        """

        # Rewards are summed during each episode for each agent, then choose the
        # max score for determining training progress/goal completion
        score = self.rewards.max()
        self.scores.append(score)

    def load_logs(self):
        """
        Loads data from on-disk log files, for later manipulation and plotting.
        """
        with open(self.paramfile, 'r') as f:
            loglines = f.read().splitlines()

        # List of the desired params to print on the graph for later review
        params_to_print = ['max_steps', 'num_episodes', 'c', 'num_atoms',
            'vmin', 'vmax', 'epsilon', 'epsilon_decay', 'epsilon_min', 'gamma',
            'learn_rate', 'buffer_size', 'batch_size', 'pretrain', 'rollout',
            'l2_decay']

        sess_params = ''
        counter = 0
        for line in loglines:
            if line.split(':')[0].lower() in params_to_print:
                line += '  '
                counter += len(line)
                if counter > 80:
                    sess_params += '\n'
                    counter = 0
                sess_params += line
        self.sess_params = sess_params

    def _moving_avg(self, data, avg_across):
        """
        Returns a curve that is the average of a noisier curve.
        """

        avg_across = int(avg_across)
        window = np.ones(avg_across)/avg_across
        data = np.pad(data, avg_across, mode="mean", stat_length=10)
        curve = np.convolve(data, window, 'same')[avg_across:-avg_across]
        return curve

    def plot_logs(self, save_to_disk=True):
        """
        Plots data in a matplotlib graph for review and comparison.
        """

        with open(self.scoresfile, 'r') as f:
            scores = np.array([float(score) for score in f.read().splitlines()])
        num_eps = len(scores)
        # Calculate the moving average, if not enough episodes were run, then
        # don't blindly average 100, but instead use the episode length as a barometer.
        score_window = max(1, int(min(100, num_eps/2)))
        # HARD VARS
        dtop = 0.85
        num_ticks = 5
        fig_scale = 10
        self.bg_color = (0.925, 0.925, 0.925)
        self.highlight_color = (0.1,0.4,0.1)
        self.highlight_alpha = 0.25
        self.ma1_color = (1, 0.2, 0.3)
        self.ma2_color = (0.38,1.0,0.55)
        self.annotate_props = dict(facecolor=(0.1,0.3,0.5), alpha=0.85,
                                   edgecolor=(0.2,0.3,0.6), linewidth=2)

        # SOFT VARS
        gs_rows = self.agent_count
        gs_cols = self.agent_count + 1
        tick_step = int(num_eps/num_ticks)
        xticks = np.linspace(0, num_eps, num_ticks, dtype=int)

        fig = plt.figure(figsize=(gs_cols*fig_scale, gs_rows/2 * fig_scale))
        fig.suptitle("{} Training Run".format(self.framework), size=40)
        gs_params = GridSpec(1,1, bottom=dtop-0.01, top=dtop)
        dummyax = fig.add_subplot(gs_params[0,0])
        dummyax.set_title(self.sess_params, size=13)
        dummyax.axis("off")
        gs = GridSpec(gs_rows, gs_cols, hspace=.5, wspace=.2, top=dtop-0.08)

        # Create the plot for the SCORES
        ax = fig.add_subplot(gs[:,0])
        self._create_scores_plot(ax, scores, score_window, num_eps, num_ticks)

        # Plot however many LOSS graphs are needed
        for col in range(1, gs_cols):
            for row in range(gs_rows):
                file = self.lossfiles[col-1][row]
                with open(file, 'r') as f:
                    data = np.array([float(loss) for loss in f.read().splitlines()])
                ax = fig.add_subplot(gs[row,col])
                label = re.match(r'(.*)_(.*)loss', file).group(2).title()
                self._create_loss_plot(ax, data, score_window, num_eps, num_ticks, xticks, label)

        if save_to_disk:
            save_file = os.path.join(self.save_dir, self.filename+"_graph.png")
            fig.savefig(save_file)
            statement = "Saved graph data to: {}".format(save_file).replace("\\", "/")
            print("{0}\n{1}\n{0}".format("#"*len(statement), statement))
        else:
            fig.show()

    def _create_scores_plot(self, ax, scores, score_window, num_eps, num_ticks):
        """
        Creates a graph plot for the SCORES of a training session.
        """
        x_axis = np.linspace(1, num_eps, num_eps)
        score_mean = scores[-score_window:].mean()
        score_std = scores[-score_window:].std()
        score_report = "{0}eps MA score: {1:.3f}\n{0}eps STD: {2:.3f}".format(
                score_window, score_mean, score_std)

        # Plot unfiltered scores
        ax.plot(x_axis, scores)
        # Plot first MA line
        ax.plot(x_axis, self._moving_avg(scores, score_window),
                color=self.ma1_color, lw=2, label="{}eps MA".format(
                score_window))
        # Plot second MA line
        ax.plot(x_axis, self._moving_avg(scores, score_window*2),
                color=self.ma2_color, lw=3, label="{}eps MA".format(
                score_window*2))

        ax.set_title("Scores")
        ax.set_xlabel("Episode")
        ax.set_xticks(np.linspace(0, num_eps, num_ticks, dtype=int))
        ax.set_ylabel("Score")
        ax.set_facecolor(self.bg_color)
        ax.grid()
        ax.legend(loc="upper left", markerscale=2.5, fontsize=15)
        ax.axvspan(x_axis[-score_window], x_axis[-1],
                   color=self.highlight_color, alpha=self.highlight_alpha)
        ax.annotate(score_report, xy=(1,1), xycoords="figure points",
                    xytext=(0.925,0.05), textcoords="axes fraction",
                    horizontalalignment="right", size=20, color='white',
                    bbox = self.annotate_props)

    def _create_loss_plot(self, ax, data, score_window, num_eps, num_ticks, xticks, label):
        """
        Creates a standardized graph plot of LOSSES for a training session.
        """
        datapoints = len(data)
        x_axis = np.linspace(1, datapoints, datapoints)
        yticks = np.linspace(min(data), max(data), num_ticks)
        ratio = datapoints / num_eps
        fitted_x = max(1, score_window * ratio)
        ma1_data = self._moving_avg(data, fitted_x)
        ma2_data = self._moving_avg(data, fitted_x*2)
        mean = data[-int(fitted_x):].mean()
        std = data[-int(fitted_x):].std()
        report = "{0}eps MA actor loss: {1:.3f}\n{0}eps STD: {2:.4f}".format(
                score_window, mean, std)

        # Plot unfiltered loss data
        ax.plot(x_axis, data)
        # Plot first MA line
        ax.plot(x_axis, ma1_data, color=self.ma1_color, lw=2,
                label="{}eps MA".format(score_window))
        # Plot second MA line
        ax.plot(x_axis, ma2_data, color=self.ma2_color, lw=3,
                label="{}eps MA".format(score_window*2))

        ax.set_xticks(np.linspace(0, datapoints, num_ticks))
        ax.set_xticklabels(xticks)
        ax.set_yticks(yticks)
        ax.set_title("{} Loss".format(label))
        ax.set_ylabel("Loss", labelpad=15)
        ax.set_facecolor(self.bg_color)
        ax.grid()
        ax.legend(loc="upper left", markerscale=1.5, fontsize=12)
        ax.axvspan(x_axis[-int(fitted_x)], x_axis[-1],
                    color=self.highlight_color, alpha=self.highlight_alpha)
        ax.annotate(report, xy=(0,0), xycoords="figure points",
                     xytext=(.935,.79), textcoords="axes fraction",
                     horizontalalignment="right", size=14, color='white',
                     bbox = self.annotate_props)

    def graph(self, logdir=None, save_to_disk=True):
        """
        Preps filepaths and then loads data from on-disk logs. Then graphs them
        for review. If SAVE_TO_DISK is False, then a graph will be popped up but
        not saved. Default is to save to disk and not do a pop-up.
        """

        if logdir != None:
            self.log_dir = logdir
            # self.filename = os.path.basename(logdir)
            self.filename = logdir.split('/')[-2]
            self.framework = self.filename.split('_')[0]
            loss_list = []
            for file in os.listdir(self.log_dir):
                file = os.path.join(self.log_dir,file).replace('\\','/')
                if file.endswith("_LOG.txt"):
                    self.paramfile = file
                elif file.endswith("_scores.txt"):
                    self.scoresfile = file
                elif file.endswith("loss.txt"):
                    loss_list.append(file)
            for file in loss_list:
                idx = int(re.search(r'agent(\d*)', file).group(1)) - 1
                try:
                    self.lossfiles[idx].append(file)
                except:
                    self.lossfiles[idx] = [file]
        self.load_logs()
        self.plot_logs(save_to_disk)

    def _generate_logfiles(self, multi_agent):
        """
        Creates empty files for later writing. Creating the empty files isn't
        strictly necessary at this point, but it feels neater.
        """

        self.scoresfile = self.logs_basename + "_scores.txt"
        open(self.scoresfile, 'a').close() # create empty scores file
        self.lossfiles = {}
        statement = []
        for idx, agent in enumerate(multi_agent.agents):
            self.lossfiles[idx] = []
            for name in self._get_agentlog_names(idx, agent):
                file = self.logs_basename + name
                self.lossfiles[idx].append(file)
                open(file, 'a').close() #create empty loss log
                statement.append(file)
        return statement

    def _init_logs(self, params, multi_agent):
        """
        Outputs an initial log of all parameters provided as a list. Initialize
        blank logs for scores, and agent losses.
        """

        # Create the log files. Params is filled on creation, the others are
        # initialized blank and filled as training proceeds.
        leader = "..."
        self.paramfile = self.logs_basename + "_LOG.txt"
        log_statement = ["Logfiles saved to: {}/".format(self.log_dir)]
        log_statement.append(leader + os.path.basename(self.paramfile))
        with open(self.paramfile, 'w') as f:
            for line in params:
                f.write(line + '\n')
        files = self._generate_logfiles(multi_agent)
        # log_statement.append(leader + os.path.basename(file))
        for file in files:
            log_statement.append(leader + os.path.basename(file))
        print_bracketing(log_statement, center=False)

    def _get_agentlog_names(self, idx, agent):
        """
        Creates a unique filename for each agent.
        Param AGENT is currently not used, but is left in for future, more
        robust file naming by pulling network names from the agent instead of
        hardcoded by hand as in the current implmementation.
        """
        idx = idx + 1
        actorlossfile = "_agent{}_actorloss.txt".format(idx)
        criticlossfile = "_agent{}_criticloss.txt".format(idx)
        return (actorlossfile, criticlossfile)

    def _collect_params(self, args, multi_agent):
        """
        Creates a list of all the Params used to run this training instance,
        prints this list to the command line if QUIET is not flagged, and stores
        it for later saving to the params log in the /logs/ directory.
        """

        param_list = [self._format_param(arg, args) for arg in vars(args) if arg not in vars(multi_agent)]
        param_list += [self._format_param(arg, multi_agent) for arg in vars(multi_agent)]
        # Manually collect agent networks for now, figure a more elegant way
        # later!
        for agent in multi_agent.agents:
            param_list += [self._format_param(arg, agent) for arg in vars(agent) if (arg not in vars(multi_agent)) and (arg not in vars(args))]
        if not self.quietmode: print_bracketing(param_list)
        return param_list

    def _format_param(self, arg, args):
        """
        Formats into PARAM: VALUE for reporting. Strips leading underscores for
        placeholder params where @properties are used for the real value.
        """

        return "{}: {}".format(arg.upper().lstrip("_"), getattr(args, arg))

    def _runtime(self, eps_num):
        """
        Return the time since the previous episode, as well as total time for
        the training session.
        """

        current_time = time.time()
        eps_time = self._format_time(current_time, self.prev_timestamp)
        total_time = self._format_time(current_time, self.start_time)
        projected_end = (self.max_eps / eps_num) * (current_time - self.start_time) + self.start_time
        # remaining = self._format_time(projected_end, self.prev_timestamp)
        remaining = self._format_time(projected_end, current_time)

        self.prev_timestamp = current_time
        return eps_time, total_time, remaining

    def _format_time(self, current, previous):
        """
        Formats time difference into Hours, Minutes, Seconds.
        """

        m, s = divmod(current - previous, 60)
        h, m = divmod(m, 60)
        return "{}h{}m{}s".format(int(h), int(m), int(s))

    def _write_losses(self, multi_agent):
        """
        Writes actor/critic loss data to file.
        """

        for idx, agent in enumerate(multi_agent.agents):
            for filename in self.lossfiles[idx]:
                if "actorloss" in filename:
                    loss = agent.actor_loss
                elif "criticloss" in filename:
                    loss = agent.critic_loss
                else:
                    raise ValueError
                with open(filename, 'a') as f:
                    f.write(str(loss) + '\n')

    def _write_scores(self):
        """
        Writes score data to file.
        """

        with open(self.scoresfile, 'a') as f:
            f.write(str(self.latest_score) + '\n')

    def _reset_rewards(self):
        """
        Resets the REWARDS list to zero for starting an episode.
        """

        self.rewards = np.zeros(self.agent_count)



def gather_args():
    """
    Generate arguments passed from the command line.
    """
    parser = ArgumentParser(description="Continuous control environment for Udacity DeepRL course.",
            usage="")

    parser.add_argument("-alr", "--actor_learn_rate",
            help="Actor Learning Rate.",
            type=float,
            default=0.001)
    parser.add_argument("-clr", "--critic_learn_rate",
            help="Critic Learning Rate.",
            type=float,
            default=0.001)
    parser.add_argument("-bs", "--batch_size",
            help="Size of each batch between learning updates",
            type=int,
            default=128)
    parser.add_argument("-buffer", "--buffer_size",
            help="How many past timesteps to keep in memory.",
            type=int,
            default=300000)
    parser.add_argument("-C", "--C",
            help="How many timesteps between hard network updates.",
            type=int,
            default=2000)
    parser.add_argument("-cpu", "--cpu",
            help="Run training on the CPU instead of the default (GPU).",
            action="store_true")
    parser.add_argument("-e", "--e",
            help="Noisey exploration rate.",
            type=float,
            default=0.3)
    parser.add_argument("-vmin", "--vmin",
            help="Min value of reward projection.",
            type=float,
            default=0)
    parser.add_argument("-vmax", "--vmax",
            help="Max value of reward projection.",
            type=float,
            default=0.25)
    parser.add_argument("-atoms", "--num_atoms",
            help="Number of atoms to project categorically.",
            type=int,
            default=51)
    parser.add_argument("-eval", "--eval",
            help="Run in evalutation mode. Otherwise, will utilize \
                  training mode. In default EVAL mode, NUM_EPISODES is set \
                  to 1 and MAX_STEPS to 1000.",
            action="store_true")
    parser.add_argument("-feval", "--force_eval",
            help="Force evaluation mode to run with specified NUM_EPISODES \
                  and MAX_STEPS param.",
            action="store_true")
    parser.add_argument("-gamma",
            help="Gamma (Discount rate).",
            type=float,
            default=0.99)
    parser.add_argument("--nographics",
            help="Run Unity environment without graphics displayed.",
            action="store_true")
    parser.add_argument("-num", "--num_episodes",
            help="How many episodes to train?",
            type=int,
            default=1000)
    parser.add_argument("-pre", "--pretrain",
            help="How many trajectories to randomly sample into the \
                  ReplayBuffer before training begins.",
            type=int,
            default=500)
    parser.add_argument("--quiet",
            help="Print less while running the agent.",
            action="store_true")
    parser.add_argument("--resume",
            help="Resume training from a checkpoint.",
            action="store_true")
    parser.add_argument("-roll", "--rollout",
            help="How many experiences to use in N-Step returns",
            type=int,
            default=5)
    parser.add_argument("-pe", "--print_every",
            help="How many episodes between print updates.",
            type=int,
            default=10)
    parser.add_argument("-le", "--log_every",
            help="How many timesteps between logging loss values.",
            type=int,
            default=15)
    parser.add_argument("-se", "--save_every",
            help="How many episodes between saves.",
            type=int,
            default=100)
    parser.add_argument("-t", "--tau",
            help="Soft network update weighting.",
            type=float,
            default=0.001)
    parser.add_argument("-utype", "--update_type",
            help="What type of target network updating to use? (HARD/SOFT) If \
                  HARD, network updates every C timesteps, if SOFT then \
                  network updates using the TAU parameter. Case insensitive.",
            type=str,
            default="hard")

    ### DEBUG: LATEST and FILENAME flags are currently disabled until time
    ### permits further development for loading/saving. Currently, saved weights
    ### can be loaded via the cmdline prompt for each agent, fairly intuitively
    ### although requiring more user input than strictly desired.
    # parser.add_argument("--latest",
    #         help="Use this flag to automatically use the latest save file \
    #               to run in DEMO mode (instead of choosing from a prompt).",
    #         action="store_true")
    # parser.add_argument("-file", "--filename",
    #         help="Path agent weights file to load. ",
    #         type=str,
    #         default=None)
    parser.add_argument("-savedir", "--save_dir",
            help="Directory to find saved agent weights.",
            type=str,
            default="saves")
    args = parser.parse_args()

    ############################################################################
    #             PROCESS ARGS AFTER COMMAND LINE GATHERING                    #

    # Check Update Type
    args.update_type = args.update_type.lower()
    assert args.update_type in ['hard','soft'], "UPDATE_TYPE must be either \
            HARD or SOFT."
    # Pretrain length can't be less than batch_size
    assert args.pretrain >= args.batch_size, "PRETRAIN less than BATCHSIZE."
    # Ensure that ROLLOUT is 1 or greater
    assert args.rollout >= 1, "ROLLOUT must be greater than or equal to 1."
    # Always use GPU if available
    args.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    # Limit the length of evaluation runs unless user forces cmdline args
    if args.eval and not args.force_eval:
        args.num_episodes = 1
        args.max_steps = 1000
    # To avoid redundant code checks elsewhere, EVAL should be set to True if
    # FORCE_EVAL is flagged
    if args.force_eval:
        args.eval = True
    args.train = not args.eval

    return args
