from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import numpy as np

from d3rlpy.argument_utility import (
    ActionScalerArg,
    EncoderArg,
    QFuncArg,
    RewardScalerArg,
    ScalerArg,
    UseGPUArg,
    check_encoder,
    check_q_func,
    check_use_gpu,
)
from d3rlpy.constants import IMPL_NOT_INITIALIZED_ERROR, ActionSpace
from d3rlpy.dataset import Transition, TransitionMiniBatch
from d3rlpy.dynamics import DynamicsBase
from d3rlpy.gpu import Device
from d3rlpy.models.encoders import EncoderFactory
from d3rlpy.models.optimizers import AdamFactory, OptimizerFactory
from d3rlpy.models.q_functions import QFunctionFactory
from d3rlpy.algos.base import AlgoBase
#from d3rlpy.algos.torch.sac_impl import SACImpl
from d3rlpy.algos.utility import ModelBaseMixin

# TH 20220203
from sac_modTH_impl import SACModTHImpl

class MOPOModTH(ModelBaseMixin, AlgoBase):
    r"""Model-based Offline Policy Optimization.
    MOPO is a model-based RL approach for offline policy optimization.
    MOPO leverages the probablistic ensemble dynamics model to generate
    new dynamics data with uncertainty penalties.
    The ensemble dynamics model consists of :math:`N` probablistic models
    :math:`\{T_{\theta_i}\}_{i=1}^N`.
    At each epoch, new transitions are generated via randomly picked dynamics
    model :math:`T_\theta`.
    .. math::
        s_{t+1}, r_{t+1} \sim T_\theta(s_t, a_t)
    where :math:`s_t \sim D` for the first step, otherwise :math:`s_t` is the
    previous generated observation, and :math:`a_t \sim \pi(\cdot|s_t)`.
    The generated :math:`r_{t+1}` would be far from the ground truth if the
    actions sampled from the policy function is out-of-distribution.
    Thus, the uncertainty penalty reguralizes this bias.
    .. math::
        \tilde{r_{t+1}} = r_{t+1} - \lambda \max_{i=1}^N
            || \Sigma_i (s_t, a_t) ||
    where :math:`\Sigma(s_t, a_t)` is the estimated variance.
    Finally, the generated transitions
    :math:`(s_t, a_t, \tilde{r_{t+1}}, s_{t+1})` are appended to dataset
    :math:`D`.
    This generation process starts with randomly sampled
    ``n_initial_transitions`` transitions till ``horizon`` steps.
    Note:
        Currently, MOPO only supports vector observations.
    References:
        * `Yu et al., MOPO: Model-based Offline Policy Optimization.
          <https://arxiv.org/abs/2005.13239>`_
    Args:
        actor_learning_rate (float): learning rate for policy function.
        critic_learning_rate (float): learning rate for Q functions.
        temp_learning_rate (float): learning rate for temperature parameter.
        actor_optim_factory (d3rlpy.models.optimizers.OptimizerFactory):
            optimizer factory for the actor.
        critic_optim_factory (d3rlpy.models.optimizers.OptimizerFactory):
            optimizer factory for the critic.
        temp_optim_factory (d3rlpy.models.optimizers.OptimizerFactory):
            optimizer factory for the temperature.
        actor_encoder_factory (d3rlpy.models.encoders.EncoderFactory or str):
            encoder factory for the actor.
        critic_encoder_factory (d3rlpy.models.encoders.EncoderFactory or str):
            encoder factory for the critic.
        q_func_factory (d3rlpy.models.q_functions.QFunctionFactory or str):
            Q function factory.
        batch_size (int): mini-batch size.
        n_frames (int): the number of frames to stack for image observation.
        n_steps (int): N-step TD calculation.
        gamma (float): discount factor.
        tau (float): target network synchronization coefficiency.
        n_critics (int): the number of Q functions for ensemble.
        update_actor_interval (int): interval to update policy function.
        initial_temperature (float): initial temperature value.
        dynamics (d3rlpy.dynamics.DynamicsBase): dynamics object.
        rollout_interval (int): the number of steps before rollout.
        rollout_horizon (int): the rollout step length.
        rollout_batch_size (int): the number of initial transitions for
            rollout.
        lam (float): :math:`\lambda` for uncertainty penalties.
        real_ratio (float): the real of dataset samples in a mini-batch.
        generated_maxlen (int): the maximum number of generated samples.
        use_gpu (bool, int or d3rlpy.gpu.Device):
            flag to use GPU, device ID or device.
        scaler (d3rlpy.preprocessing.Scaler or str): preprocessor.
            The available options are `['pixel', 'min_max', 'standard']`.
        action_scaler (d3rlpy.preprocessing.ActionScaler or str):
            action preprocessor. The available options are ``['min_max']``.
        reward_scaler (d3rlpy.preprocessing.RewardScaler or str):
            reward preprocessor. The available options are
            ``['clip', 'min_max', 'standard']``.
        impl (d3rlpy.algos.torch.sac_impl.SACImpl): algorithm implementation.
    """

    _actor_learning_rate: float
    _critic_learning_rate: float
    _temp_learning_rate: float
    _actor_optim_factory: OptimizerFactory
    _critic_optim_factory: OptimizerFactory
    _temp_optim_factory: OptimizerFactory
    _actor_encoder_factory: EncoderFactory
    _critic_encoder_factory: EncoderFactory
    _q_func_factory: QFunctionFactory
    _tau: float
    _n_critics: int
    _update_actor_interval: int
    _initial_temperature: float
    _dynamics: Optional[DynamicsBase]
    _rollout_interval: int
    _rollout_horizon: int
    _rollout_batch_size: int
    _lam: float
    _use_gpu: Optional[Device]
    #_impl: Optional[SACModTHImpl]

    # TH 20220203
    _impl: Optional[SACModTHImpl]
    _entropy_target: float


    def __init__(
        self,
        *,
        actor_learning_rate: float = 3e-4,
        critic_learning_rate: float = 3e-4,
        temp_learning_rate: float = 3e-4,
        actor_optim_factory: OptimizerFactory = AdamFactory(),
        critic_optim_factory: OptimizerFactory = AdamFactory(),
        temp_optim_factory: OptimizerFactory = AdamFactory(),
        actor_encoder_factory: EncoderArg = "default",
        critic_encoder_factory: EncoderArg = "default",
        q_func_factory: QFuncArg = "mean",
        batch_size: int = 100,
        n_frames: int = 1,
        n_steps: int = 1,
        gamma: float = 0.99,
        tau: float = 0.005,
        n_critics: int = 2,
        update_actor_interval: int = 1,
        initial_temperature: float = 1.0,
        dynamics: Optional[DynamicsBase] = None,
        rollout_interval: int = 1000,
        rollout_horizon: int = 5,
        rollout_batch_size: int = 50000,
        lam: float = 1.0,
        real_ratio: float = 0.05,
        generated_maxlen: int = 50000 * 5 * 5,
        use_gpu: UseGPUArg = False,
        scaler: ScalerArg = None,
        action_scaler: ActionScalerArg = None,
        reward_scaler: RewardScalerArg = None,
        # TH 20220203
        impl: Optional[SACModTHImpl] = None,
        entropy_target: float = None,
        termination_fn = None,
        **kwargs: Any
    ):
        super().__init__(
            batch_size=batch_size,
            n_frames=n_frames,
            n_steps=n_steps,
            gamma=gamma,
            scaler=scaler,
            action_scaler=action_scaler,
            reward_scaler=reward_scaler,
            real_ratio=real_ratio,
            generated_maxlen=generated_maxlen,
            kwargs=kwargs,
        )
        self._actor_learning_rate = actor_learning_rate
        self._critic_learning_rate = critic_learning_rate
        self._temp_learning_rate = temp_learning_rate
        self._actor_optim_factory = actor_optim_factory
        self._critic_optim_factory = critic_optim_factory
        self._temp_optim_factory = temp_optim_factory
        self._actor_encoder_factory = check_encoder(actor_encoder_factory)
        self._critic_encoder_factory = check_encoder(critic_encoder_factory)
        self._q_func_factory = check_q_func(q_func_factory)
        self._tau = tau
        self._n_critics = n_critics
        self._update_actor_interval = update_actor_interval
        self._initial_temperature = initial_temperature
        self._dynamics = dynamics
        self._rollout_interval = rollout_interval
        self._rollout_horizon = rollout_horizon
        self._rollout_batch_size = rollout_batch_size
        self._lam = lam
        self._use_gpu = check_use_gpu(use_gpu)
        self._impl = impl
        # TH 20220203
        self._entropy_target = entropy_target
        self._termination_fn = termination_fn
        assert termination_fn is not None, "termination functions should be given."

    def _create_impl(
        self, observation_shape: Sequence[int], action_size: int
    ) -> None:
        self._impl = SACModTHImpl(
            observation_shape=observation_shape,
            action_size=action_size,
            actor_learning_rate=self._actor_learning_rate,
            critic_learning_rate=self._critic_learning_rate,
            temp_learning_rate=self._temp_learning_rate,
            actor_optim_factory=self._actor_optim_factory,
            critic_optim_factory=self._critic_optim_factory,
            temp_optim_factory=self._temp_optim_factory,
            actor_encoder_factory=self._actor_encoder_factory,
            critic_encoder_factory=self._critic_encoder_factory,
            q_func_factory=self._q_func_factory,
            gamma=self._gamma,
            tau=self._tau,
            n_critics=self._n_critics,
            initial_temperature=self._initial_temperature,
            use_gpu=self._use_gpu,
            scaler=self._scaler,
            action_scaler=self._action_scaler,
            reward_scaler=self._reward_scaler,
            # TH 20220203
            entropy_target=self._entropy_target
        )
        self._impl.build()

    def _update(self, batch: TransitionMiniBatch) -> Dict[str, float]:
        assert self._impl is not None, IMPL_NOT_INITIALIZED_ERROR
        metrics = {}

        critic_loss = self._impl.update_critic(batch)
        metrics.update({"critic_loss": critic_loss})

        # delayed policy update
        if self._grad_step % self._update_actor_interval == 0:
            actor_loss = self._impl.update_actor(batch)
            metrics.update({"actor_loss": actor_loss})

            # lagrangian parameter update for SAC temperature
            if self._temp_learning_rate > 0:
                temp_loss, temp = self._impl.update_temp(batch)
                metrics.update({"temp_loss": temp_loss, "temp": temp})

            self._impl.update_critic_target()
            self._impl.update_actor_target()

        return metrics

    def get_action_type(self) -> ActionSpace:
        return ActionSpace.CONTINUOUS

    def _is_generating_new_data(self) -> bool:
        return self._grad_step % self._rollout_interval == 0

    def _sample_initial_transitions(
        self, transitions: List[Transition]
    ) -> List[Transition]:
        # uniformly sample transitions
        n_transitions = self._rollout_batch_size
        indices = np.random.randint(len(transitions), size=n_transitions)
        return [transitions[i] for i in indices]

    def _get_rollout_horizon(self) -> int:
        return self._rollout_horizon

    def _mutate_transition(
        self,
        observations: np.ndarray,
        rewards: np.ndarray,
        variances: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        # regularize by uncertainty
        rewards -= self._lam * variances
        return observations, rewards

    # Modified part
    def generate_new_data(
        self, transitions: List[Transition]
    ) -> Optional[List[Transition]]:
        assert self._impl, IMPL_NOT_INITIALIZED_ERROR
        assert self._dynamics, DYNAMICS_NOT_GIVEN_ERROR

        if not self._is_generating_new_data():
            return None

        init_transitions = self._sample_initial_transitions(transitions)

        rets: List[Transition] = []

        # rollout
        batch = TransitionMiniBatch(init_transitions)
        observations = batch.observations
        actions = self._sample_rollout_action(observations)
        prev_transitions: List[Transition] = []
        for _ in range(self._get_rollout_horizon()):
            # predict next state
            pred = self._dynamics.predict(observations, actions, True)
            pred = cast(Tuple[np.ndarray, np.ndarray, np.ndarray], pred)
            next_observations, rewards, variances = pred

            # regularize by uncertainty
            next_observations, rewards = self._mutate_transition(
                next_observations, rewards, variances
            )

            # sample policy action
            next_actions = self._sample_rollout_action(next_observations)

            terminal = self._termination_fn(obs=observations, act=actions, next_obs=next_observations)
            #print(np.sum(terminal))

            # append new transitions
            new_transitions = []
            #for i in range(len(init_transitions)):
            for i in range(observations.shape[0]):
                transition = Transition(
                    observation_shape=self._impl.observation_shape,
                    action_size=self._impl.action_size,
                    observation=observations[i],
                    action=actions[i],
                    reward=float(rewards[i][0]),
                    next_observation=next_observations[i],
                    terminal=float(terminal[i][0]),
                    #terminal=0.0,
                )

                if prev_transitions:
                    prev_transitions[i].next_transition = transition
                    transition.prev_transition = prev_transitions[i]

                new_transitions.append(transition)
            # terminate model rollout at terminal states. TH 20220203
            next_transition = []
            for i in range(len(new_transitions)):
                if not terminal[i][0]:
                    next_transition.append(new_transitions[i])
            nonterminal_mask = ~terminal.squeeze(-1)
            #
            prev_transitions = next_transition
            rets += new_transitions
            observations = next_observations[nonterminal_mask].copy()
            actions = next_actions[nonterminal_mask].copy()

        return rets