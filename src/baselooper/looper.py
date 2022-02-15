import datetime
from dataclasses import dataclass
from typing import Dict, Union, Any, Optional, Tuple

from pydantic import Extra, root_validator, validator

from baselooper import Module, State, ModuleConfig
from baselooper.utils import full_name


def iterate_modules(modules: Dict[str, Union[Module, str]], skip_references: bool = False) -> Tuple[str, Module]:
    """ Iterator over a modules dictionary which resolves references and always yields a Module.

    :param modules: A dictionary of Modules or references of Modules
    :param skip_references: If True references will not be resolved but skipped
    """
    for key, module in modules.items():
        if isinstance(module, Module):
            yield key, module
        elif isinstance(module, str):
            reference_module = modules.get(module, None)
            if not reference_module:
                raise ValueError(f"The name '{module}' is not the key of another module.")
            if not isinstance(reference_module, Module):
                raise ValueError("The referenced model has to be an instance of Module.")
            if not skip_references:
                yield key, reference_module
        else:
            raise TypeError(f"Each value of modules must be a Module or str. Got {type(module)}.")


@dataclass
class LooperState(State):
    """ A state object containing information and flags of the looper. """

    step_iteration: int = 0
    """ Counter for the iterations in a step of the looper """

    total_iteration: int = 0
    """ Counter for the total iterations over all steps of the looper """

    stop_step: bool = False
    """ Flag indication that the current step of the looper should be stopped """

    stop_loop: bool = False
    """ Flag indication that the looper should stop """


class Looper(Module):
    """ A module which takes a list of other modules and loops over it.

    A step on a Looper module is not a single iteration of the loop but the whole loop.
    That means a single step on a Looper is a loop that might run forever.

    The state inside the loop is separated from the state outside the loop. The modules which the Looper loops over
    never see the state the lopper lives in.
    """

    def __init__(self, modules: Dict[str, Union[Module, str]], **kwargs):
        super().__init__(**kwargs)
        self.modules = modules

        # The state for the modules inside the loop
        self.inner_state: State = State()
        self.inner_state.looper_state = LooperState()

        self._iterations_per_second = None
        self._last_log_iteration_count = 0
        self._last_log_iteration_time = datetime.datetime.now()

    def initialise(self, modules: Dict[str, Module] = None):
        """ Perform initialization steps of all modules in the loop.

        Modules in the loop should not depend on modules outside the loop.
        Therefore the modules of the loop can only access other modules in the same loop.
        The given modules dictionary will be ignored.

        :param Dict[str, Module] modules: Dictionary of other modules which are already initialised
        """
        if self.name in modules.keys():
            raise RuntimeError(f"The name {self.name} is already in the key of initialized modules."
                               f"Either this module is initialised twice or an other module uses the same key.")

        looper_modules = {}
        for key, module in iterate_modules(self.modules):
            module.initialise(looper_modules)
            looper_modules[key] = module

        modules[self.name] = self

    def teardown(self, state: State):
        """ Teardown all modules in the loop.

        :param State state: The final state
        """
        for _, module in iterate_modules(self.modules, skip_references=True):
            module.teardown(self.inner_state)

    def step(self, state: State):
        """ Perform a step of the Looper on the state.

        A step on a Looper module is not a single iteration of the loop but the whole loop.
        That means a single step on a Looper might be a loop that runs forever.

        :param State state: The current state
        """
        if hasattr(state, self.name) and getattr(state, self.name) is not self.inner_state:
            self.logger.warning(f"There is already a field with the name {self.name} on the state "
                                f"and it is not the state of this module. It will be overwritten."
                                f"This can happen after loading the state or "
                                f"when another modules writes on the same field name.")
        # Add the inner state as module state to the outer state
        setattr(state, self.name, self.inner_state)

        looper_state: LooperState = self.inner_state.looper_state

        # Reset step counter and flag
        looper_state.step_iteration = 0
        looper_state.stop_step = False

        while not (looper_state.stop_loop or looper_state.stop_step):
            looper_state.step_iteration += 1
            looper_state.total_iteration += 1
            for _, module in iterate_modules(self.modules):
                module.step(self.inner_state)
                if looper_state.stop_loop or looper_state.stop_step:
                    return
            self.step_callback_modules()
            self.log(state)

    def step_callback_modules(self):
        """ Call the callbacks of all included modules. """
        for _, module in iterate_modules(self.modules, skip_references=True):
            module.step_callback(self.inner_state)

    def log(self, state: State):
        """ Log information from the Looper and from all included modules.

        :param State state: The current state
        """
        super().log(state)
        for _, module in iterate_modules(self.modules, skip_references=True):
            module.log(self.inner_state)

    def _log(self, state: State) -> None:
        iterations_since_last_log = self.inner_state.looper_state.total_iteration - self._last_log_iteration_count
        now = datetime.datetime.now()
        time_since_last_log = now - self._last_log_iteration_time

        self._last_log_iteration_count = self.inner_state.looper_state.total_iteration
        self._last_log_iteration_time = now

        iterations_per_second = iterations_since_last_log / time_since_last_log.total_seconds()

        try:
            self._iterations_per_second = self._iterations_per_second * 0.9 + iterations_per_second * 0.1
        except TypeError:
            self._iterations_per_second = iterations_per_second

        self.logger.info(f"Doing {self._iterations_per_second:0.2f} iterations per second")

    def state_dict(self) -> Dict[str, Any]:
        state_dict = super(Looper, self).state_dict()

        modules_states = {}
        for key, module in self.modules.items():
            if isinstance(module, str):
                modules_states[key] = module
            else:
                modules_states[key] = module.state_dict()

        state_dict.update({
            'state': self.inner_state,
            '_last_log_iteration_count': self._last_log_iteration_count,
            '_last_log_iteration_time': self._last_log_iteration_time,
            '_iterations_per_second': self._iterations_per_second,
            'modules': modules_states,
        })
        return state_dict

    def load_state_dict(self, state_dict: Dict[str, any], strict: bool = True):
        for key, module_state_dict in state_dict['modules'].items():
            if key not in self.modules.keys():
                if strict:
                    raise ValueError(f"The module key {key} in the given state dict does not exist.")
                else:
                    self.logger.warning(f"The module key {key} in the given state dict does not exist.")

            if isinstance(module_state_dict, str):
                self.modules[key] = module_state_dict
            else:
                self.modules[key].load_state_dict(module_state_dict)

        self.inner_state = state_dict['state']
        self._last_log_iteration_count = state_dict['_last_log_iteration_count']
        self._last_log_iteration_time = state_dict['_last_log_iteration_time']
        self._iterations_per_second = state_dict['_iterations_per_second']

        super(Looper, self).load_state_dict(state_dict, strict)


class LooperConfig(ModuleConfig, extra=Extra.allow):
    modules: Dict[str, Union[ModuleConfig, str]] = {}

    def load(self, *args, **kwargs):
        all_model_field_names = {field.name for field in self.__fields__.values()}
        all_model_field_names.update({field.alias for field in self.__fields__.values()})
        extra_keys = set(self.dict()).difference(all_model_field_names)

        modules: Dict[str, Union[ModuleConfig, str]] = self.modules

        for extra_key in extra_keys:
            if extra_key in modules:
                raise ValueError(f"The name {extra_key} is used in the modules dictionary and in the extra keys. "
                                 f"It can not be used in both.")
            modules[extra_key] = getattr(self, extra_key)
            delattr(self, extra_key)

        config_data = dict(self)
        modules: Dict[str, Union[ModuleConfig, str]] = config_data['modules']
        loaded_modules = {}
        for key, module_config in modules.items():
            if isinstance(module_config, str):
                loaded_modules[key] = module_config
            else:
                loaded_modules[key] = module_config.load()
        config_data['modules'] = loaded_modules
        return Looper(**config_data)

    @root_validator(pre=True)
    def put_extra_in_modules(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        all_model_field_names = {field.name for field in cls.__fields__.values()}
        all_model_field_names.update({field.alias for field in cls.__fields__.values()})

        extra_keys = set(values).difference(all_model_field_names)

        modules: Dict[str, Union[ModuleConfig, str]] = values.get('modules', {})

        for extra_key in extra_keys:
            if extra_key in modules:
                raise ValueError(f"The name {extra_key} is used in the modules dictionary and in the extra keys. "
                                 f"It can not be used in both.")
            if not isinstance(values[extra_key], (ModuleConfig, str)):
                raise ValueError(f"extra key can only contain str or ModuleConfig "
                                 f"but got {type(values[extra_key])} for {extra_key}")

        return values

    @validator('modules')
    def check_references_are_included(cls, modules):
        module_config_keys = {k for k, v in modules.items() if isinstance(v, ModuleConfig)}
        references = {v for k, v in modules.items() if isinstance(v, str)}

        for reference in references:
            if reference not in module_config_keys:
                raise ValueError(f"{reference} is used as reference but there is no module with this name.")
        return modules


class LooperIterationStop(Module):
    def __init__(self, step_iteration_limit: Optional[int] = None,
                 total_iteration_limit: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        self.step_iteration_limit = step_iteration_limit
        self.total_iteration_limit = total_iteration_limit

    def step(self, state: State) -> None:
        looper_state: LooperState = state.looper_state
        if self.step_iteration_limit and looper_state.step_iteration >= self.step_iteration_limit:
            looper_state.stop_step = True
        if self.total_iteration_limit and looper_state.total_iteration >= self.total_iteration_limit:
            looper_state.stop_loop = True

    def state_dict(self) -> Dict[str, Any]:
        state_dict = super(LooperIterationStop, self).state_dict()

        state_dict[full_name(self)] = {
            'step_iteration_limit': self.step_iteration_limit,
            'total_iteration_limit': self.total_iteration_limit
        }
        return state_dict

    def load_state_dict(self, state_dict: Dict[str, any], strict: bool = True):
        name = full_name(self)
        if name not in state_dict.keys():
            raise ValueError(f"Expected the state dict to have a key '{name}' but it has not.")
        own_state_dict: Dict[str, Any] = state_dict.pop(name)
        self.step_iteration_limit = own_state_dict['step_iteration_limit']
        self.total_iteration_limit = own_state_dict['total_iteration_limit']

        super(LooperIterationStop, self).load_state_dict(state_dict, strict)


class LooperIterationStopConfig(ModuleConfig):
    step_iteration_limit: Optional[int] = None
    total_iteration_limit: Optional[int] = None

    def load(self, *args, **kwargs):
        return LooperIterationStop(**dict(self))
