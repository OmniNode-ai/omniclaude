# Owner(s): ["oncall: quantization"]

import logging

from quantization.core.test_backend_config import TestBackendConfig  # noqa: F401

# 2. Quantized Functional/Workflow Ops
from quantization.core.test_quantized_functional import (  # noqa: F401
    TestQuantizedFunctionalOps,
)
from quantization.core.test_quantized_module import (  # noqa: F401
    TestDynamicQuantizedModule,
    TestReferenceQuantizedModule,
    TestStaticQuantizedModule,
)

# 1. Quantized Kernels
# TODO: merge the different quantized op tests into one test class
from quantization.core.test_quantized_op import TestComparatorOps  # noqa: F401
from quantization.core.test_quantized_op import TestDynamicQuantizedOps  # noqa: F401
from quantization.core.test_quantized_op import TestPadding  # noqa: F401
from quantization.core.test_quantized_op import TestQNNPackOps  # noqa: F401
from quantization.core.test_quantized_op import TestQuantizedConv  # noqa: F401
from quantization.core.test_quantized_op import TestQuantizedEmbeddingOps  # noqa: F401
from quantization.core.test_quantized_op import TestQuantizedLinear  # noqa: F401
from quantization.core.test_quantized_op import TestQuantizedOps  # noqa: F401

# 3. Quantized Tensor
from quantization.core.test_quantized_tensor import TestQuantizedTensor  # noqa: F401
from quantization.core.test_utils import TestUtils  # noqa: F401

# 4. Modules
from quantization.core.test_workflow_module import TestDistributed  # noqa: F401
from quantization.core.test_workflow_module import TestFakeQuantize  # noqa: F401
from quantization.core.test_workflow_module import TestHistogramObserver  # noqa: F401
from quantization.core.test_workflow_module import TestObserver  # noqa: F401
from quantization.core.test_workflow_module import (  # noqa: F401
    TestFusedObsFakeQuantModule,
    TestRecordHistogramObserver,
)
from quantization.core.test_workflow_ops import TestFakeQuantizeOps  # noqa: F401
from quantization.core.test_workflow_ops import TestFusedObsFakeQuant  # noqa: F401
from quantization.eager.test_bias_correction_eager import (  # noqa: F401
    TestBiasCorrectionEager,
)

# 6. Equalization and Bias Correction
from quantization.eager.test_equalize_eager import TestEqualizeEager  # noqa: F401

# 3. Eager mode fusion passes
from quantization.eager.test_fuse_eager import TestFuseEager  # noqa: F401

# 4. Testing model numerics between quantized and FP32 models
from quantization.eager.test_model_numerics import TestModelNumericsEager  # noqa: F401

# 5. Tooling: numeric_suite
from quantization.eager.test_numeric_suite_eager import (  # noqa: F401
    TestNumericSuiteEager,
)

# 1. Eager mode post training quantization
from quantization.eager.test_quantize_eager_ptq import (  # noqa: F401
    TestQuantizeEagerOps,
    TestQuantizeEagerPTQDynamic,
    TestQuantizeEagerPTQStatic,
)

# 2. Eager mode quantization aware training
from quantization.eager.test_quantize_eager_qat import (  # noqa: F401
    TestQuantizeEagerQAT,
    TestQuantizeEagerQATNumerics,
)
from torch.testing._internal.common_utils import run_tests

# Quantization core tests. These include tests for
# - quantized kernels
# - quantized functional operators
# - quantized workflow modules
# - quantized workflow operators
# - quantized tensor


# Eager Mode Workflow. Tests for the functionality of APIs and different features implemented
# using eager mode.


log = logging.getLogger(__name__)
# FX GraphModule Graph Mode Quantization. Tests for the functionality of APIs and different features implemented
# using fx quantization.
try:
    from quantization.fx.test_quantize_fx import TestFuseFx  # noqa: F401
    from quantization.fx.test_quantize_fx import TestQuantizeFx  # noqa: F401
    from quantization.fx.test_quantize_fx import TestQuantizeFxModels  # noqa: F401
    from quantization.fx.test_quantize_fx import TestQuantizeFxOps  # noqa: F401
    from quantization.fx.test_subgraph_rewriter import (  # noqa: F401
        TestSubgraphRewriter,
    )
except ImportError as e:
    # In FBCode we separate FX out into a separate target for the sake of dev
    # velocity. These are covered by a separate test target `quantization_fx`
    log.warning(e)  # noqa:G200

# PyTorch 2 Export Quantization
try:
    # To be moved to compiler side later
    from quantization.pt2e.test_duplicate_dq import TestDuplicateDQPass  # noqa: F401
    from quantization.pt2e.test_graph_utils import TestGraphUtils  # noqa: F401
    from quantization.pt2e.test_metadata_porting import (  # noqa: F401
        TestMetaDataPorting,
    )
    from quantization.pt2e.test_numeric_debugger import (  # noqa: F401
        TestNumericDebugger,
    )
    from quantization.pt2e.test_quantize_pt2e import TestQuantizePT2E  # noqa: F401
    from quantization.pt2e.test_quantize_pt2e import (  # noqa: F401
        TestQuantizePT2EAffineQuantization,
    )

    # TODO: Figure out a way to merge all QAT tests in one TestCase
    from quantization.pt2e.test_quantize_pt2e_qat import (  # noqa: F401
        TestQuantizePT2EQAT_ConvBn1d,
        TestQuantizePT2EQAT_ConvBn2d,
        TestQuantizePT2EQATModels,
    )
    from quantization.pt2e.test_representation import (  # noqa: F401
        TestPT2ERepresentation,
    )
    from quantization.pt2e.test_x86inductor_quantizer import (  # noqa: F401
        TestQuantizePT2EX86Inductor,
    )
    from quantization.pt2e.test_xnnpack_quantizer import (  # noqa: F401
        TestXNNPACKQuantizer,
        TestXNNPACKQuantizerModels,
    )
except ImportError as e:
    # In FBCode we separate PT2 out into a separate target for the sake of dev
    # velocity. These are covered by a separate test target `quantization_pt2e`
    log.warning(e)  # noqa:G200

try:
    from quantization.fx.test_numeric_suite_fx import TestFXGraphMatcher  # noqa: F401
    from quantization.fx.test_numeric_suite_fx import (  # noqa: F401
        TestFXGraphMatcherModels,
        TestFXNumericSuiteCoreAPIs,
        TestFXNumericSuiteCoreAPIsModels,
        TestFXNumericSuiteNShadows,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200

# Test the model report module
try:
    from quantization.fx.test_model_report_fx import TestFxDetectOutliers  # noqa: F401
    from quantization.fx.test_model_report_fx import (  # noqa: F401
        TestFxDetectInputWeightEqualization,
        TestFxModelReportClass,
        TestFxModelReportDetectDynamicStatic,
        TestFxModelReportDetector,
        TestFxModelReportObserver,
        TestFxModelReportVisualizer,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200

# Equalization for FX mode
try:
    from quantization.fx.test_equalize_fx import TestEqualizeFx  # noqa: F401
except ImportError as e:
    log.warning(e)  # noqa:G200

# Backward Compatibility. Tests serialization and BC for quantized modules.
try:
    from quantization.bc.test_backward_compatibility import (  # noqa: F401
        TestSerialization,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200

from quantization.ao_migration.test_ao_migration import (  # noqa: F401
    TestAOMigrationNNIntrinsic,
    TestAOMigrationNNQuantized,
)

# AO Migration tests
from quantization.ao_migration.test_quantization import (  # noqa: F401
    TestAOMigrationQuantization,
)
from quantization.jit.test_deprecated_jit_quant import (  # noqa: F401
    TestDeprecatedJitQuantized,
)

# Quantization specific fusion passes
from quantization.jit.test_fusion_passes import TestFusionPasses  # noqa: F401

# JIT Graph Mode Quantization
from quantization.jit.test_quantize_jit import TestQuantizeDynamicJitOps  # noqa: F401
from quantization.jit.test_quantize_jit import TestQuantizeJit  # noqa: F401
from quantization.jit.test_quantize_jit import TestQuantizeJitOps  # noqa: F401
from quantization.jit.test_quantize_jit import TestQuantizeJitPasses  # noqa: F401
from quantization.jit.test_quantize_jit import (  # noqa: F401
    TestQuantizeDynamicJitPasses,
)

try:
    from quantization.ao_migration.test_quantization_fx import (  # noqa: F401
        TestAOMigrationQuantizationFx,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200

# Experimental functionality
try:
    from quantization.core.experimental.test_bits import TestBitsCPU  # noqa: F401
except ImportError as e:
    log.warning(e)  # noqa:G200
try:
    from quantization.core.experimental.test_bits import TestBitsCUDA  # noqa: F401
except ImportError as e:
    log.warning(e)  # noqa:G200
try:
    from quantization.core.experimental.test_floatx import (  # noqa: F401
        TestFloat8DtypeCPU,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200
try:
    from quantization.core.experimental.test_floatx import (  # noqa: F401
        TestFloat8DtypeCUDA,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200
try:
    from quantization.core.experimental.test_floatx import (  # noqa: F401
        TestFloat8DtypeCPUOnlyCPU,
    )
except ImportError as e:
    log.warning(e)  # noqa:G200

if __name__ == "__main__":
    run_tests()
