# XTP (eXtensible Test Script Language) - VisionCore Edge AI User Manual

## 1. Overview
This manual provides the architectural specification and configuration guidelines for testing the **VisionCore Edge AI Chip** series using **XTP (eXtensible Test Script Language)**. 

XTP allows test engineers to evaluate chip performance across dynamic voltage corners, low-power states, and tight strobe timings while providing multi-grade yield binning.

---

## 2. Architecture & Block Reference

Every XTP test script for the VisionCore processor consists of six core structural blocks:

| Block Name | Description | Key Configuration Parameters |
| :--- | :--- | :--- |
| `PINMAP` | Maps chip signals to ATE channel types. | Pin names, Signal types (`POWER`, `GROUND`, `INPUT`, `OUTPUT`, `INOUT`) |
| `LEVELS` | Configures core supply voltages and pin logic thresholds. | $V_{DD\_CORE}$, $V_{IH}$, $V_{IL}$, $V_{OH}$, $V_{OL}$ |
| `TIMING` | Establishes master clock frequencies and strobe phases. | `period_ns`, `drive_high_ns`, `drive_low_ns`, `strobe_ns` |
| `PARAMETRICS` | Specifies analog leakage and supply current bounds. | $I_{IH}$, $I_{IL}$, $I_{DDQ}$ |
| `FUNCTIONS` | Defines cycle-by-cycle digital logic vectors. | Cycle vector tuples `(CAM_CLK, MIPI_DATA, ALERT_N)` |
| `BINNING` | Maps test results to hardware sorting and software yield bins. | `SoftBin`, `HardBin` |

---

## 3. VisionCore Binning Convention

Test outcomes are classified into **Hard Bins** (physical handler binning) and **Soft Bins** (software analytics & grade classification).

### Hard Bins (Physical Destinations)
* **`HB_1` (PASS):** Silicon fully functional under evaluated test conditions.
* **`HB_2` (DIODE_FAIL):** Physical contact, open-circuit, or ESD diode failure.
* **`HB_3` (POWER_FAIL):** Parametric current limit violation ($I_{DDQ}$ quiescent current or pin leakage).
* **`HB_4` (TIMING_FAIL):** Vector mismatch or propagation delay failure during output strobe.

### Soft Bins (Software Yield Classifications)
* **`SB_1001` (PASS_PRIME):** High-performance full-power pass grade.
* **`SB_1003` (PASS_ECO_MODE):** Low-power / sub-voltage operational grade.
* **`SB_2001` (FAIL_DIODE):** Pin contact or continuity check failed.
* **`SB_3001` (FAIL_POWER):** Excess quiescent supply current ($I_{DDQ}$) or leakage current ($I_{IH} / I_{IL}$).
* **`SB_4001` (FAIL_TIMING):** Output signal transition exceeded allowable strobe window delay.

---

## 4. XTP Test Program Implementations

### Program 1: `VisionCore_V1_Standard.xtp`
Designed for nominal performance evaluation ($1.20	ext{V}$ core voltage, $4.2	ext{ns}$ output strobe window).

```python
from xtp_framework import XTPProgram

# Initialize Program: Nominal Performance Test
app = XTPProgram(name="VisionCore_V1_Standard")

# 1. PINMAP BLOCK
app.define_pinmap({
    "VDD_CORE": "POWER",
    "GND":      "GROUND",
    "CAM_CLK":  "INPUT",
    "MIPI_DATA": "INOUT",
    "ALERT_N":   "OUTPUT"
})

# 2. LEVELS BLOCK (Nominal 1.20V Core)
app.define_levels({
    "VDD_CORE": 1.20,  # Supply voltage (V)
    "VIH":      0.84,  # Input High Voltage (V)
    "VIL":      0.36,  # Input Low Voltage (V)
    "VOH":      0.96,  # Output High Compare threshold (V)
    "VOL":      0.24   # Output Low Compare threshold (V)
})

# 3. TIMING & WAVEFORMS (200 MHz Clock, 4.2ns Strobe)
app.define_timing(
    period_ns=5.0,     # 5.0 ns period (200 MHz)
    waveforms={
        "CAM_CLK":   {"drive_high_ns": 0.0, "drive_low_ns": 2.5},
        "MIPI_DATA": {"drive_data_ns": 0.0},
        "ALERT_N":   {"strobe_ns": 4.2} # Relaxed strobe window
    }
)

# 4. PARAMETRIC TESTS
app.define_parametrics({
    "Iih_Max_uA":  10.0,   # Max input leakage current (uA)
    "Iil_Min_uA": -10.0,   # Min input leakage current (uA)
    "Iddq_Max_mA": 25.0    # Max quiescent current (mA)
})

# 5. FUNCTIONAL PATTERNS
app.add_functional_pattern("Frame_Sync_Pat", vectors=[
    # Pattern Vector: (CAM_CLK, MIPI_DATA, ALERT_N)
    (0, "Z", "H"),
    (1, "1", "H"),
    (0, "0", "L")
])

# 6. BINNING ASSIGNMENTS
app.assign_bins({
    "PASS_PRIME":  {"SoftBin": 1001, "HardBin": 1},
    "FAIL_DIODE":  {"SoftBin": 2001, "HardBin": 2},
    "FAIL_POWER":  {"SoftBin": 3001, "HardBin": 3},
    "FAIL_TIMING": {"SoftBin": 4001, "HardBin": 4}
})
```

---

### Program 2: `VisionCore_V2_UltraLowPower.xtp`
Configured for under-voltage stress evaluation ($0.95	ext{V}$ core voltage, $3.1	ext{ns}$ tightened output strobe window).

```python
from xtp_framework import XTPProgram

# Initialize Program: Low-Power Corner Test
app = XTPProgram(name="VisionCore_V2_UltraLowPower")

# 1. PINMAP BLOCK
app.define_pinmap({
    "VDD_CORE": "POWER",
    "GND":      "GROUND",
    "CAM_CLK":  "INPUT",
    "MIPI_DATA": "INOUT",
    "ALERT_N":   "OUTPUT"
})

# 2. LEVELS BLOCK (Under-voltage Corner: 0.95V)
app.define_levels({
    "VDD_CORE": 0.95,  # Reduced core voltage for low-power mode
    "VIH":      0.68,
    "VIL":      0.28,
    "VOH":      0.76,
    "VOL":      0.19
})

# 3. TIMING & WAVEFORMS (Tightened Strobe Window)
app.define_timing(
    period_ns=5.0,
    waveforms={
        "CAM_CLK":   {"drive_high_ns": 0.0, "drive_low_ns": 2.5},
        "MIPI_DATA": {"drive_data_ns": 0.0},
        "ALERT_N":   {"strobe_ns": 3.1} # Strobe window pulled in to 3.1 ns
    }
)

# 4. PARAMETRIC TESTS (Strict Power Envelope)
app.define_parametrics({
    "Iih_Max_uA":   2.0,   # Tightened input leakage limit (uA)
    "Iil_Min_uA":  -2.0,
    "Iddq_Max_mA":  8.0    # Strict quiescent current target (mA)
})

# 5. FUNCTIONAL PATTERNS
app.add_functional_pattern("Frame_Sync_Pat", vectors=[
    (0, "Z", "H"),
    (1, "1", "H"),
    (0, "0", "L")
])

# 6. BINNING ASSIGNMENTS (Includes Eco-Mode Downbinning)
app.assign_bins({
    "PASS_PRIME":    {"SoftBin": 1001, "HardBin": 1},
    "PASS_ECO_MODE": {"SoftBin": 1003, "HardBin": 1}, # New Eco-Mode bin
    "FAIL_DIODE":    {"SoftBin": 2001, "HardBin": 2},
    "FAIL_POWER":    {"SoftBin": 3001, "HardBin": 3},
    "FAIL_TIMING":   {"SoftBin": 4001, "HardBin": 4}
})
```

---

## 5. Bin2Bin Transition Analysis

Cross-testing 22 VisionCore units across `VisionCore_V1_Standard.xtp` (Program A) and `VisionCore_V2_UltraLowPower.xtp` (Program B) yields the following correlation results:

### Transition Matrix Table

| Program A Bin $\rightarrow$<br>Program B Bin $\downarrow$ | **SB_1001**<br>*(Prime Pass)* | **SB_2001**<br>*(Diode Fail)* | **SB_3001**<br>*(Power Fail)* | **SB_4001**<br>*(Timing Fail)* | **Total (Prog A)** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **SB_1001** *(Prime Pass)* | **15** | 0 | 0 | 0 | **15** |
| **SB_1003** *(Eco-Mode Pass)* | **2** | 0 | 0 | 0 | **2** |
| **SB_2001** *(Diode Fail)* | 0 | **1** | 0 | 0 | **1** |
| **SB_3001** *(Power Fail)* | **1** | 0 | **1** | 0 | **2** |
| **SB_4001** *(Timing Fail)* | **1** | 0 | 0 | **1** | **2** |
| **Total (Prog B)** | **19** | **1** | **1** | **1** | **22** |

### Transition Dynamics
1. **Eco-Mode Binning ($1001 \rightarrow 1003$):** **2 units** that passed under nominal supply voltage were re-classified to `SB_1003` under low-voltage corner operating rules.
2. **Voltage-Induced Propagation Failure ($1001 \rightarrow 4001$):** **1 unit** failed the $3.1\text{ns}$ strobe timing in Program B due to increased transistor gate delay at $0.95\text{V}$.
3. **Power Envelope Violation ($1001 \rightarrow 3001$):** **1 unit** failed due to exceeding the strict $8.0\text{mA}$ supply current target in Program B.
4. **Hard Defect Stability ($2001, 3001, 4001$):** Physical open/short, gross leakage, and vector logic failures binned consistently across both programs.