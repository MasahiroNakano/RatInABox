# Environments that implement tasks
# -----# -----# -----# -----# ----------
#
# Key OpenAI Gym defines:
# (1) step()
# (2) reset()

import numpy as np

import matplotlib.pyplot as plt

import pettingzoo
import gymnasium as gym
from gymnasium.spaces import Box, Space, Dict
# see https://gymnasium.farama.org/
# see https://

from types import FunctionType
from typing import List, Union
from functools import partial
import warnings
from copy import copy

from ratinabox.Environment import Environment
from ratinabox.Agent import Agent

class Reward():
    """
    When an task goal is triggered, reward goal is attached an Agent's
    reward:list. This object tracks the dynamics of the reward applied to the
    agent.

    This implementation allows rewards to be applied:
        - externally (through a task environment) 
        - or internally (through the agent's internal neuronal dynamics),
          e.g. through a set of neurons tracking rewards, attached to the agent

    This tracker specifies what the animals reward value should be at a given
    time while the reward is activate
    """
    decay_preset = {
        "constant":    lambda a, x: a,
        "linear":      lambda a, x: a * x,
        "exponential": lambda a, x: a * np.exp(x),
        "none":        lambda a, x: 0
    }
    decay_knobs_preset = {
        "linear":      [1],
        "constant":    [1],
        "exponential": [2],
        "none":        []
    }
    def __init__(self, init_state, dt,
                 expire_clock=None, decay=None,
                 decay_knobs=[], 
                 external_drive:Union[FunctionType,None]=None,
                 external_drive_strength=1):
        """
        Parameters
        ----------
        init_state : float
            initial reward value
        dt : float
            timestep
        expire_clock : float|None
            time until reward expires, if None, reward never expires
        decay : str|function|None
            decay function, or decay preset name, or None
        decay_knobs : list
            decay function knobs
        external_drive : function|None
            external drive function, or None. can be used to attach a goal
            gradient or reward ramping signal
        external_drive_strength : float
            strength of external drive, how quickly the reward follows the
            external drive
        """
        self.state = init_state if not isinstance(init_state, FunctionType) \
                               else init_state()
        self.dt = dt
        self.expire_clock = expire_clock if \
                isinstance(expire_clock, (int,float)) else \
                dt
        if isinstance(decay, str):
            self.preset = decay
            self.decay_knobs = decay_knobs or self.decay_knobs_preset[self.preset]
            self.decay = partial(self.decay_preset[self.preset], *self.decay_knobs)
        else:
            self.preset = "custom" if decay is not None \
                                   else "constant"
            self.decay_knobs = decay_knobs or \
                                        self.decay_knobs_preset[self.preset]
            self.decay = decay or self.decay_preset["constant"]
        self.external_drive = external_drive
        self.external_drive_strength = external_drive_strength
        self.history = {'state':[], 'expire_clock':[]}

    def update(self):
        """
        update reward, 

        grows towards the gradient target value from its initial value, if a
        target_value() function is defined. otherwise, reward is only
        controlled by decay from some initial value. if decay is 0, and target
        gradient is not defined then its constant, until the reward expire time
        is reached.

        # Returns
        True if reward is still active, False if reward has expired
        """
        self.state = self.state + self.get_delta() * self.dt
        self.expire_clock -= self.dt
        self.history['state'].append(self.state)
        self.history['expire_clock'].append(self.expire_clock)
        return not (self.expire_clock <= 0)

    def get_delta(self, state=None):
        """ \delta(reward) for a dt """
        state = self.state if state is None else state
        if self.external_drive is not None:
            target_gradient = self.external_drive()
            strength = self.external_drive_strength
            change = (strength*(target_gradient - state) - self.decay(state)) 
        else:
            change = -(self.decay(state)) 
        return change

    def plot_theoretical_reward(self, timerange=(0,1)):
        """
        plot the reward dynamics : shows the user how their parameters of
        interest setup reward dynamics, without updating the object
        """
        rewards = [self.state]
        timesteps = np.arange(timerange[0], timerange[1], self.dt)
        for t in timesteps[1:]:
            r = rewards[-1] + self.get_delta(state=rewards[-1]) * self.dt
            rewards.append(r)
        plt.plot(timesteps, rewards[:len(timesteps)],
               label=f"reward={self.preset}, " 
               f"knobs={self.decay_knobs}")
        plt.axvspan(self.expire_clock, plt.gca().get_ylim()[-1], color='r', 
                    alpha=0.2)
        plt.text(np.mean((plt.gca().get_xlim()[0], self.expire_clock)), 
                 np.mean(plt.gca().get_ylim()), "reward\nactive",
                 backgroundcolor='black', color="white")
        plt.text(np.mean((self.expire_clock, plt.gca().get_xlim()[-1])), 
                 np.mean(plt.gca().get_ylim()), "reward\nexpires",
                 backgroundcolor='black', color="white")
        plt.gca().set(xlabel="time (s)", ylabel="reward signal")
        return plt.gcf(), plt.gca()

class RewardCache():
    """
    RewardCache

    A cache of all `active` rewards attached to an agent
    """
    def __init__(self, verbose=False):
        self.cache:List[Reward] = []
        self.verbose = verbose

    def append(self, reward:Reward, copymode=True):
        if reward is not None:
            if copymode:
                self.cache.append(copy(reward))
            else:
                self.cache.append(reward)

    def update(self):
        """
            Update
        """
        for reward in self.cache:
            reward_still_active = reward.update()
            if not reward_still_active:
                self.cache.remove(reward)
                if self.verbose:
                    print("Reward removed from cache")
    
    def get_total(self):
        """
        If there are any active rewards, return the sum of their values.
        """
        return sum([reward.state for reward in self.cache])


class TaskEnvironment(Environment, pettingzoo.ParallelEnv):
    """
    Environment with task structure: there is a goal, and when the
    goal is reached, it terminates an episode, and starts a new episode
    (reset). This environment can be static or dynamic, depending on whether
    update() is implemented.

    In order to be more useful with other Reinforcement Learning pacakges, this
    environment inherits from both ratinabox.Environment and openai's widely
    used gym environment.

    # Inputs
    --------
    *pos : list
        Positional arguments to pass to Environment
    verbose : bool
        Whether to print out information about the environment
    render_mode : str
        How to render the environment. Options are 'matplotlib', 'pygame', or
        'none'
    render_every : int
        How often to render the environment (in time steps)
    **kws :
        Keyword arguments to pass to Environment
    """
    metadata = {
        "render_modes": ["matplotlib", "none"],
        "name": "TaskEnvironment-RiAB"
    }

    def __init__(self, *pos, verbose=False,
                 render_mode='matplotlib', 
                 render_every=None, render_every_framestep=2,
                 dt=0.01, teleport_on_reset=False, 
                 save_expired_rewards=False, **kws):
        super().__init__(*pos, **kws)
        self.goals:List[Goal] = [] # list of current goals to saitsfy
        self.dynamic_walls = []      # list of walls that can change/move
        self.dynamic_objects = []    # list of current objects that can move
        self.Agents:List[Agent] = [] # list of agents in the environment
        self.t = 0                   # current time
        self.dt = dt                 # time step
        self.history = {'t':[]}      # history of the environment

        self.render_every = render_every_framestep # How often to render
        self.verbose = verbose
        self.render_mode:str = render_mode # options 'matplotlib'|'pygame'|'none'
        self._stable_render_objects:dict = {} # objects that are stable across
                                         # a rendering type

        # ----------------------------------------------
        # Agent-related task config
        # ----------------------------------------------
        self.teleport_on_reset = teleport_on_reset # Whether to teleport 
                                                   # agents to random

        # ----------------------------------------------
        # Setup gym primatives
        # ----------------------------------------------
        # Setup observation space from the Environment space
        self.observation_spaces:Dict[Space] = Dict({})
        self.action_spaces:Dict[Space]      = Dict({})
        self.reward_caches:List[RewardCache] = []
        self.agent_names:List[str]     = []
        self.info:dict                 = {} # gymnasium returns info in step()

        # Episode history
        self.episodes:dict = {} # Written to upon completion of an episode
        self.episodes['episode']  = []
        self.episodes['start']    = []
        self.episodes['end']      = []
        self.episodes['duration'] = []
        self.episode = 0

        # Reward cache specifics
        self.save_expired_rewards = save_expired_rewards
        self.expired_rewards:List[RewardCache] = []

    def observation_space(self, agent_name:str):
        return self.observation_spaces[agent_name]

    def action_space(self, agent_name:str):
        return self.action_spaces[agent_name]

    def add_agents(self, agents:Union[dict, List[Agent], Agent],
                   names:Union[None,List]=None, maxvel:float=50.0, **kws):
        """
        Add agents to the environment

        For each agent, we add its action space (expressed as velocities it can
        take) to the environment's action space.

        Parameters
        ----------
        agents : Dict[Agent] | List[Agent] | Agent
            The agents to add to the environment
        names : List[str] | None
            The names of the agents. If None, then the names are generated
        maxvel : float
            The maximum velocity that the agents can take
        """
        if not isinstance(agents, (list, Agent)):
            raise TypeError("agents must be a list of agents or an agent type")
        if isinstance(agents, Agent):
            agents = [agents]
        if not ([agent.dt == self.dt for agent in agents]):
            raise NotImplementedError("Does not yet support agents with different dt from envrionment")
        if isinstance(agents, dict):
            names  = list(agents.keys())
            agents = list(agents.values())
        elif names is None:
            start = len(self.Agents)
            names = ["agent_" + str(start+i) for i in range(len(agents))]
        # Enlist agents
        for (name, agent) in zip(names, agents):
            self.Agents.append(agent)
            self.agent_names.append(name)
            # Add the agent's action space to the environment's action spaces
            # dict
            D = int(self.dimensionality[0])
            self.action_spaces[name] = Box(low=0, high=maxvel, shape=(D,))
            # Add the agent's observation space to the environment's 
            # observation spaces dict
            ext = [self.extent[i:i+2] 
                   for i in np.arange(0, len(self.extent), 2)]
            lows, highs = np.array(list(zip(*ext)), dtype=np.float_)
            self.observation_spaces[name] = \
                    Box(low=lows, high=highs, dtype=np.float_)
            cache = RewardCache()
            self.reward_caches.append(cache)
            agent.reward = cache
            agent.t = self.t # agent clock is aligned to environment,
                             # in case a new agent is placed in the env
                             # on a later episode

    def _dict(self, V):
        """
        Convert a list of values to a dictionary of values keyed by agent name
        """
        return {name:v for (name, v) in zip(self.agent_names, V)} \
                if hasattr(V,'__iter__') else \
                {name:V for name in self.agent_names}

    def _is_terminal_state(self):
        """
        Whether the current state is a terminal state
        """
        raise NotImplementedError("_is_terminated() must be implemented")
    
    def _is_truncated_state(self):
        """ 
        whether the current state is a truncated state, 
        see https://gymnasium.farama.org/api/env/#gymnasium.Env.step

        default is false: an environment by default will have a terminal state,
        ending the episode, whereon users should call reset(), but not a
        trucation state ending the mdp.
        """
        return False

    def reset(self, seed=None, return_info=False, options=None):
        """
        How to reset the task when finisedh
        """
        if len(self.episodes['start']) > 0:
            self.write_end_episode()
        
        # Clear rendering cache
        self.clear_render_cache()

        # If teleport on reset, randomly pick new location for agents
        if self.teleport_on_reset:
            for agent in self.Agents:
                agent.update()
                agent.pos = self.observation_spaces.sample()
                agent.history['pos'][-1] = agent.pos

        # Increment episode counter
        self.episode += 1
        self.write_start_episode()

    def update(self, update_agents=False):
        """
        How to update the task over time --- update things
        directly connected to the task
        """
        self.t += self.dt # base task class only has a clock
        self.history['t'].append(self.t)

    def step(self, actions:Union[dict,np.array]=None, dt=None, 
             drift_to_random_strength_ratio=1, *pos, **kws):
        """
            step()

        step() functions in Gynasium paradigm usually take an action space
        action, and return the next state, reward, whether the state is
        terminal, and an information dict

        different from update(), which updates this environment. this function
        executes a full step on the environment with an action from the agents

        https://pettingzoo.farama.org/api/parallel/#pettingzoo.utils.env.ParallelEnv.step
        """

        # If the user passed drift_velocity, update the agents
        actions = actions if isinstance(actions, dict) else \
                  self._dict(actions)
        for (agent, action) in zip(self.Agents, actions.values()):
            dt = dt if dt is not None else agent.dt
            action = np.array(action).ravel()
            agent.update(dt=dt, drift_velocity=action,
                         drift_to_random_strength_ratio= \
                                 drift_to_random_strength_ratio)

        # Update the reward caches for time decay of existing rewards
        for reward_cache in self.reward_caches:
            reward_cache.update()

        # Udpate the environment, which can add new rewards to caches
        self.update(*pos, **kws)
        
        # Return the next state, reward, whether the state is terminal,
        return (self.get_observation(), 
                self.get_reward(), 
                self._dict(self._is_terminal_state()),
                self._dict(self._is_truncated_state()), 
                self._dict([self.info])
                )

    def step1(self, action, *pos, **kws):
        """
        shortcut for stepping when only 1 agent exists...makes it behave
        like gymnasium instead of pettingzoo
        """
        results = self.step({self.agent_names[0]:action}, *pos, **kws)
        results = [x[self.agent_names[0]] for x in results]
        return results
        
    def get_observation(self):
        """ Get the current state of the environment """
        return {name:agent.pos 
                for name, agent in zip(self.agent_names, self.Agents)}

    def get_reward(self):
        """ Get the current reward state of each agent """
        return {name:agent.reward.get_total()
                for name, agent in zip(self.agent_names, self.Agents)}

    # ----------------------------------------------
    # Reading and writing episode data
    # ----------------------------------------------
    def _current_episode_start(self):
        return 0 \
                if not len(self.episodes['start']) \
                else self.episodes['end'][-1] + self.dt

    def write_start_episode(self, **kws):
        self.episodes['episode'].append(self.episode)
        self.episodes['start'].append(self._current_episode_start())

    def write_end_episode(self, **kws):
        self.episodes['end'].append(self.t)
        self.episodes['duration'].append(self.t - \
                                         self.episodes['start'][-1])


    # ----------------------------------------------
    # Rendering
    # ----------------------------------------------
    def render(self, render_mode=None, *pos, **kws):
        """
        Render the environment
        """
        if render_mode is None:
            render_mode = self.render_mode
        # if self.verbose:
        #     print("rendering environment with mode: {}".format(render_mode))
        if render_mode == 'matplotlib':
            self._render_matplotlib(*pos, **kws)
        elif render_mode == 'pygame':
            self._render_pygame(*pos, **kws)
        elif render_mode == 'none':
            pass
        else:
            raise ValueError("method must be 'matplotlib' or 'pygame'")

    def _render_matplotlib(self, *pos, agentkws:dict=dict(), **kws):
        """
        Render the environment using matplotlib
        `
        Inputs
        ------
        agentkws: dict
            keyword arguments to pass to the agent's render method
        """

        if np.mod(self.t, self.render_every) < self.dt:
            # Skip rendering unless this is redraw time
            return False

        R = self._get_mpl_render_cache()
    
        # Render the environment
        self._render_mpl_env()

        # Render the agents
        self._render_mpl_agents(**agentkws)

        return True

    def _get_mpl_render_cache(self):
        if "matplotlib" not in self._stable_render_objects:
            R = self._stable_render_objects["matplotlib"] = {}
        else:
            R = self._stable_render_objects["matplotlib"]
        if "fig" not in R:
            fig, ax = plt.subplots(1,1)
            R["fig"] = fig
            R["ax"] = ax
        else:
            fig, ax = R["fig"], R["ax"]
        return R, fig, ax
    
    def _render_mpl_env(self):
        R, fig, ax = self._get_mpl_render_cache()
        if "environment" not in R:
            R["environment"] = self.plot_environment(fig=fig, ax=ax)
            R["title"] = fig.suptitle("t={:.2f}\nepisode={}".format(self.t, 
                                                                    self.episode))
        else:
            R["title"].set_text("t={:.2f}\nepisode={}".format(self.t,
                                                              self.episode
                                                              ))

    def _render_mpl_agents(self, framerate=60, alpha=0.7, 
                           t_start="episode", **kws):
        """
        Render the agents 🐀 

        Inputs
        ------
        framerate: float
            the framerate at which to render the agents
        alpha: float
            the alpha value to use for the agents
        t_start: float
            the time at which to start rendering the agents
                - "episode" : start at the beginning of the current episode
                - "all" : start at the beginning of the first episode
                - float : start at the given time
        **kws
            keyword arguments to pass to the agent's style (point size, color)
            see _agent_style
        """
        R, fig, ax = self._get_mpl_render_cache()
        initialize = "agents" not in R
        if t_start is "episode":
            t_start = self.episodes['start'][-1]
        elif t_start is "all" or t_start is None:
            t_start = self.episodes['start'][0]
        def get_agent_props(agent, color):
            t = np.array(agent.history['t'])
            startid = np.nanargmin(np.abs(t - (t_start)))
            skiprate = int((1.0/framerate)//agent.dt)
            trajectory = np.array(agent.history['pos'][startid::skiprate])
            t = t[startid::skiprate]
            c, s = self._agent_style(agent, t, color, startid=startid, 
                                     skiprate=skiprate, **kws)
            return trajectory, c, s
        if initialize or \
                len(R["agents"]) != len(self.Agents):
            R["agents"]        = []
            for (i, agent) in enumerate(self.Agents):
                trajectory, c, s = get_agent_props(agent, i)
                ax.scatter(*trajectory.T,
                    s=s, alpha=alpha, zorder=0, c=c, linewidth=0)
                R["agents"].append(ax.collections[-1])
        else:
            for i, agent in enumerate(self.Agents):
                scat = R["agents"][i]
                trajectory, c, s = get_agent_props(agent, i)
                scat.set_offsets(trajectory)
                scat.set_facecolors(c)
                scat.set_edgecolors(c)
                scat.set_sizes(s)

    @staticmethod
    def _agent_style(agent:Agent, time, color=0, skiprate=1, startid=0,
                     point_size:bool=15, decay_point_size:bool=False,
                     plot_agent:bool=True, decay_point_timescale:int=10):
        if isinstance(color, int):
            color=plt.rcParams['axes.prop_cycle'].by_key()['color'][color]
        s = point_size * np.ones_like(time)
        if decay_point_size == True:
            s = point_size * np.exp((time - time[-1]) / decay_point_timescale)
            s[(time[-1] - time) > (1.5 * decay_point_timescale)] *= 0
        c = [color] * len(time)
        if plot_agent == True:
            s[-1] = 40
            c[-1] = "r"
        return c, s

    def _render_pygame(self, *pos, **kws):
        pass

    def clear_render_cache(self):
        """
            clear_render_cache
        
        clears the cache of objects held for render()
        """
        if "matplotlib" in self._stable_render_objects:
            R = self._stable_render_objects["matplotlib"]
            R["ax"].cla()
            for item in (set(R.keys()) - set(("fig","ax"))):
                R.pop(item)

    def close(self):
        """ gymnasium close() method """
        self.clear_render_cache()
        if "fig" in self._stable_render_objects:
            if isinstance(self._stable_render_objects["fig"], plt.Figure):
                plt.close(self._stable_render_objects["fig"])

reward_default=Reward(1, 0.01, expire_clock=1, decay="linear")

class Goal():
    """
    Abstract `Objective` class that can be used to define finishing coditions
    for a task
    """
    def __init__(self, env:TaskEnvironment, 
                 reward=reward_default):
        self.env = env
        self.reward = reward

    def check(self, agents:Union[List[Agent],Agent,List[int],int,None]=None):
        """
        Check if the goal is satisfied

        # Returns, when implemented
        --------------------------
        Reward | None : optional reward
        agent index : to which agent?
        """
        raise NotImplementedError("check() must be implemented")

    def _agents(self, 
                   agents:Union[List[Agent],Agent,List[int],int,None]=None):
        """
        Convenience function for processing possible agents argument in 
        check()
        """
        if isinstance(agents, Agent):
            agents = [agents]
        elif isinstance(agents, int):
            agents = [self.env.Agents[agents]]
        elif agents is None:
            agents = self.env.Agents
        return agents

    def __eq__(self, other):
        raise NotImplementedError("__eq__() must be implemented")

    def __call__(self):
        """
        Can be used to report its value to the environment
        (Not required -- just a convenience)
        """
        raise NotImplementedError("__call__() must be implemented")

class GoalCache():
    """
        Organizes different ways of checking a collection of goals.
        In series or parallel? Does each agent have to finish the goal? 
        Or any?

        # Inputs
        --------
        mode : str
            Goal relations
            - "sequential"    : goal must be accomplished in sequence
            - "nonsequential" : any order
            - "custom" : provide a function that gives valid successor
                         indices for a given goal
        agentmode : str
            Agent handling
            - "interact" :: an goal is consumed/satisfied if any
                            one agent satisfies it
            - "noninteract" :: all agents must satisfy goal
    """
    def __init__(self, env, mode="parallel", agentmode="any", *pos, **kws):
        self.env       = env
        self.goals:List[Goal] =[]
        self.mode     = mode
        self.agentmode = agentmode
        # records the last goal that was achieved, if sequential
        self._if_sequential__last_acheived = {
                i:-1 for i in range(len(self.env.Agents))}

    def check(self, remove_finished:bool=True):
        """
        Check if any goals are satisfied

        # Inputs
        --------
        remove_finished : bool
            Remove finished goals from the cache?

        # Returns
        --------
        rewards : list of rewards
        agents : list of agents that satisfied the goal
        """
        # Agents must accomplish goal, following the sequence of the
        # goal list?
        if self.mode  == "sequential":
            rewards, agents = [], []
            for i, agent in enumerate(self.env.Agents):
                next = self._if_sequential__last_acheived[i] + 1
                reward, solution_agents = self.goals[next].check(agent)
                if solution_agents == i:
                    rewards.append(reward)
                    agents.append(i)
                    self._if_sequential__last_acheived[i] = next
                self._handle_agentmode(agent, remove_finished=remove_finished)
        # Agents do not have to accomplish goal in sequence, any
        # order is fine
        elif self.mode == "nonsequential":
            rewards, solution_agents = \
                    zip(*[goal.check() for goal in self.goals])
            self._handle_agentmode(solution_agents, 
                                   remove_finished=remove_finished)
        else:
            raise ValueError("Unknown mode: {}".format(self.mode))
        return rewards, agents

    def _handle_agentmode(self, solution_agents, **kws):
        if self.agentmode == "interact":
            self._agentmode_is_interact(**kws)
        elif self.agentmode == "parallel":
            self._agentmode_is_parallel(**kws)

    def _agentmode_is_interact(self, remove_finished:bool=True):
        """
        each goal, when satisfied consumes the goal for all agents
        """
        pass

    def _agentmode_is_noninteract(self):
        """
        each goal, when satisfied is only consumed for that agent
        """
        pass

    def __call__(self):
        raise NotImplementedError("__call__() must be implemented")

    def append(self, goal):
        self.goals.append(goal)

    def clear(self):
        self.goals.clear()

    def find(self, goal:Goal):
        """ Find an goal in the cache """
        for cache_goal in self.goals:
            if cache_goal == goal:
                return cache_goal

class SpatialGoal(Goal):
    """
    Spatial goal objective: agent must reach a specific position

    Parameters
    ----------
    env : TaskEnvironment
        The environment that the objective is defined in
    reward_value : float
        The reward value that the objective gives
    goal_pos : np.ndarray | None
        The position that the agent must reach
    goal_radius : float | None
        The radius around the goal position that the agent must reach
    """
    def __init__(self, *pos, reward=reward_default, goal_pos:Union[np.ndarray,None], 
                 goal_radius=None, **kws):
        super().__init__(*pos, **kws)
        if self.env.verbose:
            print("new SpatialGoal: goal_pos = {}".format(goal_pos))
        self.goal_pos = goal_pos
        self.radius = np.min((self.env.dx * 10, np.ptp(self.env.extent)/10)) if goal_radius is None else goal_radius
    
    def _in_goal_radius(self, pos, goal_pos):
        """
        Check if a position is within a radius of a goal position
        """
        radius = self.radius
        distance = lambda x,y : self.env.get_distances_between___accounting_for_environment(x, y, wall_geometry="line_of_sight")
        # return np.linalg.norm(pos - goal_pos, axis=1) < radius \
        #         if np.ndim(goal_pos) > 1 \
        #         else np.abs((pos - goal_pos)) < radius
        return distance(pos, goal_pos) < radius 

    def check(self, agents:Union[List[Agent],Agent,List[int],int,None]=None):
        """
        Check if the goal is satisfied

        Parameters
        ----------
        agents : List[Agent]
            The agents to check the goal for (usually just one)

        Returns
        -------
        rewards : List[float]
            The rewards for each agent
        which_agents : np.ndarray
            The indices of the agents that reached the goal
        """
        agents = self._agents(agents)
        agents_reached_goal = [
            self._in_goal_radius(agent.pos, self.goal_pos).all().any()
                               for agent in agents]
        rewarded_agents = np.where(agents_reached_goal)[0]
        rewards = [self.reward] * len(rewarded_agents)
        return rewards, rewarded_agents

    def __eq__(self, other:Union[Goal, np.ndarray, list]):
        if isinstance(other, SpatialGoal):
            return np.all(self.goal_pos == other.goal_pos)
        elif isinstance(other, (np.ndarray,list)):
            return np.all(self.goal_pos == np.array(other))

    def __call__(self)->np.ndarray:
        """
        Can be used to report its value to the environment
        (Not required -- just a convenience)
        """
        return np.array(self.goal_pos)


class SpatialGoalEnvironment(TaskEnvironment):
    """
    Creates a spatial goal-directed task

    Parameters
    ----------
    *pos : 
        Positional arguments for TaskEnvironment
            - n_agents : int
            - 
    possible_goal_pos : List[np.ndarray] | np.ndarray
        List of possible goal positions
    current_goal_state : np.ndarray | None
        The current goal position
    n_goals : int
        The number of goals to set
    """
    # --------------------------------------
    # Some reasonable default render settings
    # --------------------------------------
    ag_annotate_default={'fontsize':10}
    ag_scatter_default ={'marker':'o'}

    def __init__(goal_cache, *pos, 
                 reward=reward_default, goalkws=dict(),
                 possible_goal_pos:Union[List,np.ndarray,str]='random_5', 
                 current_goal_state:Union[None,np.ndarray,List[np.ndarray]]=None, 
                 n_goals:int=1,
                 **kws):
        super().__init__(*pos, **kws)
        goal_cache.possible_goals:List[SpatialGoal] = \
                goal_cache._init_poss_goal_positions(possible_goal_pos)
        goal_cache.goal_cache:GoalCache = GoalCache()
        goal_cache.n_goals = n_goals
        goal_cache.goalkws = dict()
        goal_cache.goalkws.update({'reward':reward})
        goal_cache.goalkws.update(goalkws)
        if current_goal_state is None:
            goal_cache.reset()

    def _init_poss_goal_positions(self, 
                         possible_goal_position:Union[List,np.ndarray,str]) ->list[SpatialGoal]:
        """ 
        Initialize the possible goal positions 


        Parameters
        ----------
        possible_goal_pos : List[np.ndarray] | np.ndarray | str
            List of possible goal positions or a string to generate random
            goal positions

        Returns
        -------
        possible_goal_pos : np.ndarray
        """

        if isinstance(possible_goal_position, str):
            if possible_goal_position.startswith('random'):
                n = int(possible_goal_position.split('_')[1])
                ext = [self.extent[i:i+2] 
                       for i in np.arange(0, len(self.extent), 2)]
                possible_goal_position = [np.random.random(n) * \
                                     (ext[i][1] - ext[i][0]) + ext[i][0]
                                     for i in range(len(ext))]
                possible_goal_position = np.array(possible_goal_position).T
            else:
                raise ValueError("possible_goal_pos string must start with "
                                 "'random'")
        if isinstance(possible_goal_position, (list, np.ndarray)):
            possible_goal_position = np.array(possible_goal_position)
        # Create possible Goal
        possible_goals = [SpatialGoal(self,
                                                    goal_pos=pos,
                                                    **self.goalkws)
                               for pos in possible_goal_position]
        return possible_goals


    def get_goal_positions(self):
        """ Get the current goal positions """
        return self.goal_cache.get_goals()

    def _propose_spatial_goal(self):
        """
        Propose a new spatial goal from the possible goal positions
        """
        if len(self.possible_goals):
            g = np.random.choice(np.arange(len(self.possible_goals)), 1)
            goal_pos = self.possible_goals[g]
        else:
            warnings.warn("No possible goal positions specified yet")
            goal_pos = None # No goal state (this could be, e.g., a lockout time)
        return goal_pos

    def reset(self, goal_locations:Union[np.ndarray,None]=None, n_objectives=None) ->Dict:
        """
            reset

        resets the environement to a new episode
        https://pettingzoo.farama.org/api/parallel/#pettingzoo.utils.env.ParallelEnv.reset
        """
        super().reset()


        # How many goals to set?
        if goal_locations is not None:
            ng = len(goal_locations)
        elif n_objectives is not None:
            ng = n_objectives
        else:
            ng = self.n_goals

        # Push new spatial objectives to the cache
        self.goal_cache.clear()
        # Set the number of required spatial spatial goals
        for g in range(ng):
            if goal_locations is None:
                goal_pos = self._propose_spatial_goal()
            else:
                goal_pos = self.goal_cache.find(goal_locations[g])
                if goal_pos is None:
                    raise ValueError("goal_locations must be a subset "
                      " of possible_goal_pos")

            self.goal_cache.append(goal_pos)

        return self.get_observation()

    def _is_terminal_state(self):
        """
        Whether the current state is a terminal state
        """
        # Check our objectives
        test_goal = 0
        # Loop through objectives, checking if they are satisfied
        rewards, agents = self.goal_cache.check_and_remove_satisfied()
        for reward, agent in zip(rewards, agents):
            self.reward_caches[agent].append(reward)
        # Return if no objectives left
        no_objectives_left = len(self.goal_cache) == 0
        return no_objectives_left

    def update(self, *pos, **kws):
        """
        Update the environment

        if drift_velocity is passed, update the agents
        """
        # Update the environment
        super().update(*pos, **kws)

        # Check if we are done
        if self._is_terminal_state():
            self.reset()


    # --------------------------------------
    # Rendering
    # --------------------------------------

    def _render_matplotlib(self, goalkws=dict(), **kws):
        """
        Take existing mpl render and add spatial goals
        
        Parameters
        ----------
        goalkws : dict
            keyword arguments to pass to the spatial goal rendering
        """
        if super()._render_matplotlib(**kws):
            # Render the spatial goals
            self._render_mpl_spat_goals(**goalkws)

    def _render_mpl_spat_goals(self, facecolor="red", alpha=0.1,
                               marker="x", c="red"):
        R, fig, ax = self._get_mpl_render_cache()
        initialize = "spat_goals" not in R or \
                len(self.goal_cache) != len(R["spat_goals"])
        if initialize:
            R["spat_goals"]       = []
            R["spat_goal_radius"] = []
            for spat_goal in self.goal_cache:                
                if self.dimensionality == "2D":
                    x, y = spat_goal().T
                else:
                    x, y = np.zeros(np.shape(spat_goal())), spat_goal()
                sg = plt.scatter(x,y, marker=marker, c=c)
                ci = plt.Circle(spat_goal().ravel(), spat_goal.radius,
                                facecolor=facecolor, alpha=alpha)
                ax.add_patch(ci)
                R["spat_goals"].append(sg)
                R["spat_goal_radius"].append(sg)
        else:
            for i, obj in enumerate(self.goal_cache):
                scat = R["spat_goals"][i]
                scat.set_offsets(obj())
                ci = R["spat_goal_radius"][i]
                # TODO blitting circles?
                # ci.set_center(obj().ravel())
                # ci.set_radius(obj.radius)


active = True
if active and __name__ == "__main__":

    plt.close('all')

    # Test reward class
    r1=Reward(1, dt=0.01, expire_clock=0.5, decay="linear", 
              decay_knobs=[6])
    r1.plot_theoretical_reward()

    # Test the environment
    env = SpatialGoalEnvironment(n_goals=2, params={'dimensionality':'2D'},
                                 reward=r1, render_every=1, 
                                 teleport_on_reset=False,
                                 verbose=True)
    # Create an agent
    Ag = Agent(env)
    env.add_agents(Ag) # add it to the environment
    env.reset()

    # Prep the rendering figure
    plt.ion(); env.render(); plt.show()
    plt.pause(0.1)

    # Define some helper functions
    get_goal_vector   = lambda Ag: env.get_vectors_between___accounting_for_environment(
            env.get_goal_positions()[0][0], Ag.pos)[0]

    # -----------------------------------------------------------------------
    # TEST 1 AGENT
    # -----------------------------------------------------------------------
    # Run the simulation, with the agent drifting towards the goal when
    # it is close to the goal
    # s = input("Single Agent. Press enter to start")
    reward_printed = 0
    speed = 12 # dials how fast agent runs
    pausetime = 0.000001

    while env.episode < 4:
        # Get the direction to the goal
        dir_to_reward = get_goal_vector(Ag)
        drift_velocity = speed * Ag.speed_mean * \
                (dir_to_reward / np.linalg.norm(dir_to_reward))
        # Step the environment with actions
        observation, reward, terminate_episode, _, info = \
                env.step1(drift_velocity)
        # --- Report reward to the REPL ------
        if reward > 0:
            if not reward_printed:
                print("-"*40,"Reward Initiated","-"*40)
            print("Reward_value:", reward)
            reward_printed = True
        else:
            if reward_printed:
                print("-"*40,"Reward Ended","-"*40)
            reward_printed = False
        # ------------------------------------
        # Render environment
        env.render()
        plt.pause(pausetime)
        # Check if we are done
        if terminate_episode:
            print("done! reward:", reward)
            env.reset()

    # -----------------------------------------------------------------------
    # TEST Multi-agent (2 agents, does not show reward values in terminal,
    #                   as in the above example)
    # -----------------------------------------------------------------------
    Ag2 = Agent(env)
    env.add_agents(Ag2)
    # s = input("Two agents. Press enter to start")
    print("Agent names: ",env.agent_names)
    while env.episode < 6:
        # Get the direction to the goal
        dir_to_reward = {"agent_0":get_goal_vector(Ag),
                         "agent_1":get_goal_vector(Ag2)}
        drift_velocity = {agent : speed * Ag.speed_mean * 
                (dir_to_reward / np.linalg.norm(dir_to_reward))
                for (agent, dir_to_reward) in dir_to_reward.items()}
        # Step the environment with actions
        observation, reward, terminate_episode, _, info = \
                env.step(drift_velocity)
        # Render environment
        env.render()
        plt.pause(pausetime)
        # Check if we are done
        if any(terminate_episode.values()):
            print("done! reward:", reward)
            env.reset()



