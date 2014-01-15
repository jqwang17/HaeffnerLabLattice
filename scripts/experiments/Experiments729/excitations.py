from base_excitation import base_excitation

class excitation_729(base_excitation):
    from lattice.scripts.PulseSequences.spectrum_rabi import spectrum_rabi
    name = 'Excitation729'
    pulse_sequence = spectrum_rabi

class excitation_blue_heat_rabi(base_excitation):
    from lattice.scripts.PulseSequences.blue_heat_rabi import blue_heat_rabi
    name = 'ExcitationBlueHeatRabi'
    pulse_sequence = blue_heat_rabi

class excitation_ramsey(base_excitation):
    from lattice.scripts.PulseSequences.ramsey import ramsey
    name = 'ExcitationRamsey'
    pulse_sequence = ramsey
    
class excitation_ramsey_spectrum(base_excitation):
    from lattice.scripts.PulseSequences.pulsed_scan_ramsey import pulsed_scan_ramsey
    name = 'ExcitationRamsey'
    pulse_sequence = pulsed_scan_ramsey

class excitation_dephase(base_excitation):
    from lattice.scripts.PulseSequences.dephasing_chain import dephasing_chain
    name = 'DephasingChain'
    pulse_sequence = dephasing_chain
    
if __name__ == '__main__':
    import labrad
    cxn = labrad.connect()
    scanner = cxn.scriptscanner
    exprt = excitation_dephase(cxn = cxn)
    ident = scanner.register_external_launch(exprt.name)
    exprt.execute(ident)