from torchgen.dest.lazy_ir import (
    GenLazyIR as GenLazyIR,
    GenLazyNativeFuncDefinition as GenLazyNativeFuncDefinition,
    GenLazyShapeInferenceDefinition as GenLazyShapeInferenceDefinition,
    generate_non_native_lazy_ir_nodes as generate_non_native_lazy_ir_nodes,
)
from torchgen.dest.native_functions import (
    compute_native_function_declaration as compute_native_function_declaration,
)
from torchgen.dest.register_dispatch_key import (
    RegisterDispatchKey as RegisterDispatchKey,
    gen_registration_headers as gen_registration_headers,
    gen_registration_helpers as gen_registration_helpers,
)
from torchgen.dest.ufunc import (
    compute_ufunc_cpu as compute_ufunc_cpu,
    compute_ufunc_cpu_kernel as compute_ufunc_cpu_kernel,
    compute_ufunc_cuda as compute_ufunc_cuda,
)
