package fr.local.tv.sf463.core;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/** Real host Java execution; no Android stubs, framework or external dependencies. */
public final class CoreTests {
    interface Checked {void run();}
    static void check(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
    static void equal(Object actual,Object expected) {check(actual.equals(expected),"Expected "+expected+" but got "+actual);}
    static void rejects(Checked task) {try {task.run();throw new AssertionError("Expected validation failure");}catch(IllegalArgumentException expected){}}
    static Config.Action a(String type) {return new Config.Action(type,"");}
    static final class Fixture {
        final List<String> actions=new ArrayList<>();
        final GestureEngine engine=new GestureEngine(x -> actions.add(x.type));
        final Config.Profile p=new Config.Profile("p","Test",true);
        final GestureEngine.Input key=new GestureEngine.Input(1,183,400,123,456);
        Fixture(boolean hold,boolean twice) {
            p.bindings.add(new Config.Binding(new Config.Button(183,-1,0,0,"Red"),a("hdmi1"),hold ? a("settings") : Config.Action.none(),twice ? a("self") : Config.Action.none()));engine.setProfile(p);
        }
    }
    public static void testDisabledColorPresetAndReset() {
        Config c=Config.defaults();c.validate();check(!c.active().enabled,"Preset must be disabled");
        equal(c.active().bindings.size(),4);equal(c.active().bindings.get(0).shortAction.packageName,"com.movix.tv");
        equal(c.active().bindings.get(1).shortAction.type,"hdmi1");equal(c.active().bindings.get(2).shortAction.type,"hdmi2");equal(c.active().bindings.get(3).shortAction.type,"self");
        for(Config.Binding b:c.active().bindings)check(!b.longAction.present() && !b.doubleAction.present(),"Extra gestures off by default");
        c.active().enabled=true;c.active().bindings.clear();Config reset=Config.defaults();equal(reset.active().bindings.size(),4);check(!reset.active().enabled,"Reset disabled");
    }
    public static void testLearnedIdentityOverridesWildcardWithoutMatchingOtherDevice() {
        Config.Profile p=Config.defaults().active();Config.Binding learned=new Config.Binding(new Config.Button(183,400,123,456,"Learned red"),a("settings"),a("none"),a("none"));p.bindings.add(learned);
        equal(p.find(183,400,123,456),learned);equal(p.find(183,400,124,456).shortAction.type,"app");
        equal(p.find(183,401,123,456).shortAction.type,"app");check(p.find(187,400,123,456)==null,"No unrelated key match");
    }
    public static void testProtectedKeysNeverBindOrIntercept() {
        int[] protectedKeys={0,3,4,19,20,21,22,23,24,25,26,66,84,91,164,177,219,223,224,225,231,268,269,270,271,276};Fixture f=new Fixture(true,true);
        for(int key:protectedKeys) {
            check(Config.protectedKey(key),"Missing protected key "+key);rejects(() -> new Config.Button(key,-1,0,0,"Bad"));
            GestureEngine.Input i=new GestureEngine.Input(1,key,0,0,0);check(!f.engine.down(i,0,0,false),"Essential DOWN passthrough");check(!f.engine.up(i,100,false),"Essential UP passthrough");
        }
        equal(f.actions.size(),0);
    }
    public static void testProfileCloneIsDisabledAndBindingsIndependent() {
        Config.Profile p=Config.defaults().active();p.enabled=true;Config.Profile copy=p.copy("copy","Copy");
        check(!copy.enabled,"Cloning must not activate shortcuts");copy.bindings.get(0).shortAction=a("self");equal(p.bindings.get(0).shortAction.type,"app");equal(copy.bindings.size(),4);
    }
    public static void testConfigurationBoundsAndActionsRejected() {
        rejects(() -> new Config.Action("shell",""));rejects(() -> new Config.Action("app","am start something"));rejects(() -> new Config.Action("settings","com.invalid.extra"));
        rejects(() -> new Config.Button(183,-2,0,0,"Bad"));rejects(() -> new Config.Profile("../bad","Bad",false));
        Config c=Config.defaults();c.profiles.add(c.active());rejects(c::validate);c=Config.defaults();c.activeProfileId="missing";rejects(c::validate);
    }
    public static void testShortOnReleaseNoDelayWithDoubleOffAndRepeats() {
        Fixture f=new Fixture(false,false);check(f.engine.down(f.key,0,0,false),"Capture DOWN");
        check(f.engine.down(f.key,1,100,false),"Capture repeat");equal(f.actions.size(),0);equal(f.engine.nextDeadline(),Long.MAX_VALUE);
        check(f.engine.up(f.key,200,false),"Capture UP");equal(f.actions.toString(),"[hdmi1]");f.engine.tick(2000);equal(f.actions.size(),1);
    }
    public static void testLongExactlyAt600AndNoShortOrRepeatAction() {
        Fixture f=new Fixture(true,false);f.engine.down(f.key,0,10,false);f.engine.tick(609);equal(f.actions.size(),0);equal(f.engine.nextDeadline(),610L);
        f.engine.tick(610);f.engine.down(f.key,4,800,false);f.engine.tick(2000);f.engine.up(f.key,2100,false);equal(f.actions.toString(),"[settings]");equal(f.engine.nextDeadline(),Long.MAX_VALUE);
    }
    public static void testLongReleaseBoundaryWorksWhenTimerIsLate() {
        Fixture f=new Fixture(true,false);f.engine.down(f.key,0,0,false);f.engine.up(f.key,600,false);equal(f.actions.toString(),"[settings]");
        f=new Fixture(true,false);f.engine.down(f.key,0,0,false);f.engine.up(f.key,599,false);equal(f.actions.toString(),"[hdmi1]");
    }
    public static void testDoubleWindowAndSingleDeadline() {
        Fixture f=new Fixture(false,true);f.engine.down(f.key,0,0,false);f.engine.up(f.key,20,false);f.engine.tick(319);equal(f.actions.size(),0);
        f.engine.down(f.key,0,319,false);f.engine.up(f.key,350,false);f.engine.tick(1000);equal(f.actions.toString(),"[self]");
        f=new Fixture(false,true);f.engine.down(f.key,0,0,false);f.engine.up(f.key,20,false);f.engine.tick(320);equal(f.actions.toString(),"[hdmi1]");
    }
    public static void testSecondDownAtDeadlineStartsNewSingle() {
        Fixture f=new Fixture(false,true);f.engine.down(f.key,0,0,false);f.engine.up(f.key,20,false);f.engine.down(f.key,0,320,false);f.engine.up(f.key,340,false);f.engine.tick(640);
        equal(f.actions.toString(),"[hdmi1, hdmi1]");
    }
    public static void testLongWinsOverDoubleAndDoesNotEmitShort() {
        Fixture f=new Fixture(true,true);f.engine.down(f.key,0,0,false);f.engine.up(f.key,20,false);f.engine.down(f.key,0,100,false);f.engine.tick(700);f.engine.up(f.key,750,false);f.engine.tick(2000);
        equal(f.actions.toString(),"[settings]");
    }
    public static void testProfileChangeCancelsActionButConsumesOwnedRelease() {
        Fixture f=new Fixture(true,true);f.engine.down(f.key,0,0,false);f.engine.setProfile(new Config.Profile("off","Off",false));
        check(f.engine.down(f.key,1,700,false),"Previously owned repeats consumed");check(f.engine.up(f.key,800,false),"Previously owned UP consumed");
        check(!f.engine.down(f.key,0,900,false),"New DOWN passthrough");check(!f.engine.up(f.key,950,false),"New UP passthrough");equal(f.actions.size(),0);
    }
    public static void testDisableCancelsPendingSingle() {
        Fixture f=new Fixture(false,true);f.engine.down(f.key,0,0,false);f.engine.up(f.key,20,false);f.engine.cancel();f.engine.tick(1000);equal(f.actions.size(),0);equal(f.engine.nextDeadline(),Long.MAX_VALUE);
    }
    public static void testCanceledReleaseAndOrphanEventsPassthrough() {
        Fixture f=new Fixture(true,false);check(!f.engine.up(f.key,0,false),"Orphan UP");check(!f.engine.down(f.key,2,10,false),"Orphan repeated DOWN");
        f.engine.down(f.key,0,20,false);check(f.engine.up(f.key,1000,true),"Canceled owned UP consumed");equal(f.actions.size(),0);
    }
    public static void testCompanionForegroundDoesNotCapture() {
        Fixture f=new Fixture(true,true);check(!f.engine.down(f.key,0,0,true),"Companion UI must receive its buttons");check(!f.engine.up(f.key,50,false),"Matching passthrough UP");equal(f.actions.size(),0);
    }
    public static void testFreshDownRecoversMissingReleaseWithoutStaleHold() {
        Fixture f=new Fixture(true,false);f.engine.down(f.key,0,0,false);f.engine.down(f.key,0,5000,false);
        equal(f.actions.size(),0);check(f.engine.up(f.key,5100,false),"Fresh gesture owns its UP");equal(f.actions.toString(),"[hdmi1]");
    }
    public static void testUnconfiguredAndDisabledKeysHaveNoSideEffects() {
        Fixture f=new Fixture(true,true);GestureEngine.Input other=new GestureEngine.Input(1,190,400,123,456);
        check(!f.engine.down(other,0,0,false),"Unconfigured key passthrough");f.p.enabled=false;check(!f.engine.down(f.key,0,10,false),"Disabled profile passthrough");equal(f.actions.size(),0);
    }
    public static void testTwoDevicesAndButtonsKeepIndependentOwnership() {
        Fixture f=new Fixture(false,false);GestureEngine.Input second=new GestureEngine.Input(2,183,400,123,456);
        f.engine.down(f.key,0,0,false);f.engine.down(second,0,10,false);f.engine.up(second,20,false);f.engine.up(f.key,30,false);equal(f.actions.toString(),"[hdmi1, hdmi1]");
    }
    public static void testJsonRoundTripAllActionsMultipleProfilesUnicode() {
        Config c=Config.defaults();c.active().enabled=true;c.active().name="Salon \"Été\" \\ TV";Config.Profile p=c.active().copy("other","Other");
        p.bindings.get(0).longAction=a("settings");p.bindings.get(0).doubleAction=a("couchy");c.profiles.add(p);c.activeProfileId="other";
        String wire=JsonCodec.encode(c);Config decoded=JsonCodec.decode(wire,false);equal(JsonCodec.encode(decoded),wire);equal(decoded.profiles.get(0).name,c.profiles.get(0).name);check(decoded.profiles.get(0).enabled,"Local enabled persists");
        Config imported=JsonCodec.decode(wire,true);for(Config.Profile x:imported.profiles)check(!x.enabled,"Import must disable every profile");equal(imported.activeProfileId,"other");equal(imported.active().bindings.get(0).doubleAction.type,"couchy");
    }
    public static void testJsonRejectsUnknownSchemaDuplicateKeysAndProtectedImports() {
        String s=JsonCodec.encode(Config.defaults());rejects(() -> JsonCodec.decode(s.replace("\"schemaVersion\":1","\"schemaVersion\":2"),true));
        rejects(() -> JsonCodec.decode(s.replace("\"schemaVersion\":1","\"schemaVersion\":1,\"schemaVersion\":1"),true));
        rejects(() -> JsonCodec.decode(s.replace("\"keyCode\":183","\"keyCode\":26"),true));
        rejects(() -> JsonCodec.decode(s.replace("\"hdmi1\"","\"shell\""),true));
    }
    public static void testJsonRejectsDuplicateButtonsAndUnknownActiveProfile() {
        Config c=Config.defaults();String base=JsonCodec.encode(c);c.active().bindings.add(c.active().bindings.get(0));rejects(() -> JsonCodec.encode(c));
        rejects(() -> JsonCodec.decode(base.replace("\"activeProfileId\":\"default\"","\"activeProfileId\":\"missing\""),true));
    }
    public static void testJsonRejectsMalformedAndOversizeWithoutChangingExistingConfig() {
        Config original=Config.defaults();String before=JsonCodec.encode(original);
        for(String bad:new String[]{"", "{", "[]", "{\"x\":01}","{\"x\":1.5}","{\"x\":\"\\q\"}","{\"x\":\"\\u+123\"}","{\"x\":true} garbage"}) rejects(() -> JsonCodec.decode(bad,true));
        StringBuilder big=new StringBuilder();for(int i=0;i<=JsonCodec.MAX_CHARS;i++)big.append(' ');rejects(() -> JsonCodec.decode(big.toString(),true));
        String deep="0";for(int i=0;i<18;i++)deep="["+deep+"]";final String excessive=deep;rejects(() -> JsonCodec.decode(excessive,true));equal(JsonCodec.encode(original),before);
    }
    public static void main(String[] args) throws Exception {
        Method[] methods=CoreTests.class.getDeclaredMethods();Arrays.sort(methods,Comparator.comparing(Method::getName));
        int count=0;for(Method m:methods)if(m.getName().startsWith("test")) {
            try {m.invoke(null);System.out.println("PASS "+m.getName());count++;}catch(InvocationTargetException e){throw new AssertionError(m.getName(),e.getCause());}
        }
        System.out.println(count+" host-Java tests passed");
    }
}
