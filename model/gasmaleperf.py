"""Jungle Hawk Owl"""
import numpy as np
from gpkitmodels.aircraft.GP_submodels.breguet_endurance import BreguetEndurance
from gpkitmodels.aircraft.GP_submodels.gas_engine import Engine
from gpkitmodels.aircraft.GP_submodels.wing import Wing
from gpkitmodels.aircraft.GP_submodels.fuselage import Fuselage
from gpkitmodels.aircraft.GP_submodels.empennage import Empennage
from gpkitmodels.aircraft.GP_submodels.tail_boom import TailBoomState
from gpkitmodels.aircraft.GP_submodels.tail_boom_flex import TailBoomFlexibility
from helpers import summing_vars
from gpkit import Model, Variable, Vectorize, units

# pylint: disable=invalid-name

class Aircraft(Model):
    "the JHO vehicle"
    def __init__(self, Wfueltot, DF70=False, **kwargs):
        self.flight_model = AircraftPerf
        self.fuselage = Fuselage(Wfueltot)
        self.wing = Wing()
        self.engine = Engine(DF70)
        self.empennage = Empennage()

        components = [self.fuselage, self.wing, self.engine, self.empennage]
        self.smeared_loads = [self.fuselage, self.engine]

        self.loading = AircraftLoading

        Wzfw = Variable("W_{zfw}", "lbf", "zero fuel weight")
        Wpay = Variable("W_{pay}", 10, "lbf", "payload weight")
        Ppay = Variable("P_{pay}", 10, "W", "payload power")
        Wavn = Variable("W_{avn}", 8, "lbf", "avionics weight")
        lantenna = Variable("l_{antenna}", 13.4, "in", "antenna length")
        wantenna = Variable("w_{antenna}", 10.2, "in", "antenna width")

        constraints = [
            Wzfw >= sum(summing_vars(components, "W")) + Wpay + Wavn,
            self.empennage.horizontaltail["V_h"] <= (
                self.empennage.horizontaltail["S"]
                * self.empennage.horizontaltail["l_h"]/self.wing["S"]**2
                * self.wing["b"]),
            self.empennage.verticaltail["V_v"] <= (
                self.empennage.verticaltail["S"]
                * self.empennage.verticaltail["l_v"]/self.wing["S"]
                / self.wing["b"]),
            self.wing["C_{L_{max}}"]/self.wing["m_w"] <= (
                self.empennage.horizontaltail["C_{L_{max}}"]
                / self.empennage.horizontaltail["m_h"]),
            # enforce antenna sticking on the tail
            self.empennage.verticaltail["c_{t_v}"] >= wantenna,
            self.empennage.verticaltail["b_v"] >= lantenna,
            # enforce a cruciform with the htail infront of vertical tail
            self.empennage.tailboom["l"] >= (
                self.empennage.horizontaltail["l_h"]
                + self.empennage.horizontaltail["c_{r_h}"]),
            Ppay == Ppay
            ]

        Model.__init__(self, None, [components, constraints],
                       **kwargs)

class AircraftLoading(Model):
    "aircraft loading model"
    def __init__(self, aircraft, Wcent, **kwargs):

        loading = [aircraft.wing.loading(aircraft.wing, Wcent)]
        loading.append(aircraft.empennage.loading(aircraft.empennage))
        loading.append(aircraft.fuselage.loading(aircraft.fuselage, Wcent))

        tbstate = TailBoomState()
        loading.append(TailBoomFlexibility(aircraft.empennage.horizontaltail,
                                           aircraft.empennage.tailboom,
                                           aircraft.wing, tbstate, **kwargs))

        Model.__init__(self, None, loading, **kwargs)

class AircraftPerf(Model):
    "performance model for aircraft"
    def __init__(self, static, state, **kwargs):

        self.wing = static.wing.flight_model(static.wing, state)
        self.fuselage = static.fuselage.flight_model(static.fuselage, state)
        self.engine = static.engine.flight_model(static.engine, state)
        self.htail = static.empennage.horizontaltail.flight_model(
            static.empennage.horizontaltail, state)
        self.vtail = static.empennage.verticaltail.flight_model(
            static.empennage.verticaltail, state)
        self.tailboom = static.empennage.tailboom.flight_model(
            static.empennage.tailboom, state)

        self.dynamicmodels = [self.wing, self.fuselage, self.engine,
                              self.htail, self.vtail, self.tailboom]
        areadragmodel = [self.fuselage, self.htail, self.vtail, self.tailboom]
        areadragcomps = [static.fuselage, static.empennage.horizontaltail,
                         static.empennage.verticaltail,
                         static.empennage.tailboom]

        Wend = Variable("W_{end}", "lbf", "vector-end weight")
        Wstart = Variable("W_{start}", "lbf", "vector-begin weight")
        CD = Variable("C_D", "-", "drag coefficient")
        CDA = Variable("CDA", "-", "area drag coefficient")
        mfac = Variable("m_{fac}", 1.7, "-", "drag margin factor")

        dvars = []
        for dc, dm in zip(areadragcomps, areadragmodel):
            if "C_f" in dm.varkeys:
                dvars.append(dm["C_f"]*dc["S"]/static.wing["S"])

        constraints = [Wend == Wend,
                       Wstart == Wstart,
                       CDA/mfac >= sum(dvars),
                       CD >= CDA + self.wing["C_d"]]

        Model.__init__(self, None, [self.dynamicmodels, constraints], **kwargs)

class FlightState(Model):
    "define environment state during a portion of an aircraft mission"
    def __init__(self, alt, wind, **kwargs):

        rho = Variable("\\rho", "kg/m^3", "air density")
        h = Variable("h", alt, "ft", "altitude")
        href = Variable("h_{ref}", 15000, "ft", "Reference altitude")
        psl = Variable("p_{sl}", 101325, "Pa", "Pressure at sea level")
        Latm = Variable("L_{atm}", 0.0065, "K/m", "Temperature lapse rate")
        Tsl = Variable("T_{sl}", 288.15, "K", "Temperature at sea level")
        temp = [(t.value - l.value*v.value).magnitude
                for t, v, l in zip(Tsl, h, Latm)]
        Tatm = Variable("t_{atm}", temp, "K", "Air temperature")
        mu = Variable("\\mu", "N*s/m^2", "Dynamic viscosity")
        musl = Variable("\\mu_{sl}", 1.789*10**-5, "N*s/m^2",
                        "Dynamic viscosity at sea level")
        Rspec = Variable("R_{spec}", 287.058, "J/kg/K",
                         "Specific gas constant of air")

        # Atmospheric variation with altitude (valid from 0-7km of altitude)
        constraints = [rho == psl*Tatm**(5.257-1)/Rspec/(Tsl**5.257),
                       (mu/musl)**0.1 == 0.991*(h/href)**(-0.00529),
                       h == h,
                       href == href]

        V = Variable("V", "m/s", "true airspeed")

        if wind:

            V_wind = Variable("V_{wind}", 25, "m/s", "Wind speed")
            constraints.extend([V >= V_wind])

        else:

            V_wind = Variable("V_{wind}", "m/s", "Wind speed")
            V_ref = Variable("V_{ref}", 25, "m/s", "Reference wind speed")

            constraints.extend([(V_wind/V_ref) >= 0.6462*(h/href) + 0.3538,
                                V >= V_wind])
        Model.__init__(self, None, constraints, **kwargs)

class FlightSegment(Model):
    "creates flight segment for aircraft"
    def __init__(self, N, aircraft, alt=15000, wind=False,
                 etap=0.7, **kwargs):

        self.aircraft = aircraft

        with Vectorize(N):
            self.fs = FlightState(alt, wind)
            self.aircraftPerf = self.aircraft.flight_model(self.aircraft,
                                                           self.fs)
            self.slf = SteadyLevelFlight(self.fs, self.aircraft,
                                         self.aircraftPerf, etap)
            self.be = BreguetEndurance(self.aircraftPerf)

        self.submodels = [self.fs, self.aircraftPerf, self.slf, self.be]

        Wfuelfs = Variable("W_{fuel-fs}", "lbf", "flight segment fuel weight")

        self.constraints = [Wfuelfs >= self.be["W_{fuel}"].sum()]

        if N > 1:
            self.constraints.extend([self.aircraftPerf["W_{end}"][:-1] >=
                                     self.aircraftPerf["W_{start}"][1:]])

        Model.__init__(self, None, [self.aircraft, self.submodels,
                                    self.constraints], **kwargs)

class Loiter(Model):
    "make a loiter flight segment"
    def __init__(self, N, aircraft, alt=15000, wind=False,
                 etap=0.7, **kwargs):
        fs = FlightSegment(N, aircraft, alt, wind, etap)

        t = Variable("t", "days", "time loitering")
        constraints = [fs.be["t"] >= t/N]

        Model.__init__(self, None, [constraints, fs], **kwargs)

class Cruise(Model):
    "make a cruise flight segment"
    def __init__(self, N, aircraft, alt=15000, wind=False, etap=0.7, R=200):
        fs = FlightSegment(N, aircraft, alt, wind, etap)

        R = Variable("R", R, "nautical_miles", "Range to station")
        constraints = [R/N <= fs["V"]*fs.be["t"]]

        Model.__init__(self, None, [fs, constraints])

class Climb(Model):
    "make a climb flight segment"
    def __init__(self, N, aircraft, alt=15000, wind=False, etap=0.7, dh=15000):
        fs = FlightSegment(N, aircraft, alt, wind, etap)

        with Vectorize(N):
            hdot = Variable("\\dot{h}", "ft/min", "Climb rate")

        deltah = Variable("\\Delta_h", dh, "ft", "altitude difference")
        hdotmin = Variable("\\dot{h}_{min}", 100, "ft/min",
                           "minimum climb rate")

        constraints = [
            hdot*fs.be["t"] >= deltah/N,
            hdot >= hdotmin,
            fs.slf["T"] >= (0.5*fs["\\rho"]*fs["V"]**2*fs["C_D"]
                            * fs.aircraft.wing["S"] + fs["W_{start}"]*hdot
                            / fs["V"]),
            ]

        Model.__init__(self, None, [fs, constraints])

class SteadyLevelFlight(Model):
    "steady level flight model"
    def __init__(self, state, aircraft, perf, etap, **kwargs):

        T = Variable("T", "N", "thrust")
        etaprop = Variable("\\eta_{prop}", etap, "-", "propulsive efficiency")

        constraints = [
            (perf["W_{end}"]*perf["W_{start}"])**0.5 <= (
                0.5*state["\\rho"]*state["V"]**2*perf["C_L"]
                * aircraft.wing["S"]),
            T >= (0.5*state["\\rho"]*state["V"]**2*perf["C_D"]
                  *aircraft.wing["S"]),
            perf["P_{shaft}"] >= T*state["V"]/etaprop]

        Model.__init__(self, None, constraints, **kwargs)

class Mission(Model):
    "creates flight profile"
    def __init__(self, DF70=False, wind=False, **kwargs):

        mtow = Variable("MTOW", "lbf", "max-take off weight")
        Wcent = Variable("W_{cent}", "lbf", "center aircraft weight")
        Wfueltot = Variable("W_{fuel-tot}", "lbf", "total aircraft fuel weight")
        LS = Variable("(W/S)", "lbf/ft**2", "wing loading")

        JHO = Aircraft(Wfueltot, DF70)
        loading = JHO.loading(JHO, Wcent)

        climb1 = Climb(10, JHO, alt=np.linspace(0, 15000, 11)[1:], etap=0.508, wind=wind)
        cruise1 = Cruise(1, JHO, etap=0.684, R=180, wind=wind)
        loiter1 = Loiter(5, JHO, etap=0.647, wind=wind)
        cruise2 = Cruise(1, JHO, etap=0.684, wind=wind)
        mission = [climb1, cruise1, loiter1, cruise2]

        constraints = [
            mtow >= climb1["W_{start}"][0],
            Wfueltot >= sum(fs["W_{fuel-fs}"] for fs in mission),
            mission[-1]["W_{end}"][-1] >= JHO["W_{zfw}"],
            Wcent >= Wfueltot + sum(summing_vars(JHO.smeared_loads, "W")),
            LS == mtow/JHO.wing["S"],
            loiter1["P_{total}"] >= (loiter1["P_{shaft}"] + (
                loiter1["P_{avn}"] + JHO["P_{pay}"])
                                     / loiter1["\\eta_{alternator}"])
            ]

        for i, fs in enumerate(mission[1:]):
            constraints.extend([
                mission[i]["W_{end}"][-1] == fs["W_{start}"][0]
                ])

        cost = 1/loiter1["t_Mission, Loiter"]

        Model.__init__(self, cost, [JHO, mission, loading, constraints],
                       **kwargs)

if __name__ == "__main__":
    M = Mission(DF70=True)
    subs = {"b": 24, "l_Mission, Aircraft, Empennage, TailBoom": 7.0,
            "AR_v": 1.5, "AR": 24, "SM_{corr}": 0.5, "AR_h": 4}
    M.substitutions.update(subs)
    for p in M.varkeys["P_{avn}"]:
        M.substitutions.update({p: 65})
    # JHO.debug(solver="mosek")
    sol = M.solve("mosek")
    print sol.table()
    # Lamv = np.arctan(sol("c_{r_v}")*(1-0.7)/sol("b_v")/0.75)*180/np.pi

