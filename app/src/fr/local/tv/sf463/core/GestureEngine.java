package fr.local.tv.sf463.core;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

/** All clocks are injected monotonic milliseconds. tick() runs only while a deadline exists. */
public final class GestureEngine {
    public interface Sink { void dispatch(Config.Action action); }
    public static final class Input {
        public final int device, key, scan, vendor, product;
        public Input(int device, int key, int scan, int vendor, int product) { this.device=device; this.key=key; this.scan=scan; this.vendor=vendor; this.product=product; }
        String token() { return device+":"+key+":"+scan; }
    }
    private static final class Press {
        Config.Binding binding; long down; boolean fired, canceled, second;
        Press(Config.Binding b, long now, boolean second) { binding=b; down=now; this.second=second; }
    }
    private static final class Pending {
        Config.Binding binding; long due;
        Pending(Config.Binding b, long due) { binding=b; this.due=due; }
    }
    private final Sink sink;
    private final Map<String,Press> held = new HashMap<>();
    private final Map<String,Pending> singles = new HashMap<>();
    private Config.Profile profile;
    public GestureEngine(Sink sink) { this.sink=sink; }
    public void setProfile(Config.Profile next) {
        singles.clear(); for (Press p : held.values()) p.canceled=true; profile=next;
    }
    public boolean down(Input key, int repeats, long now, boolean uiForeground) {
        String token=key.token();
        // A fresh DOWN after a missing UP starts a new gesture; do not fire a stale hold.
        if (held.containsKey(token) && repeats==0) held.remove(token);
        tick(now);
        if (held.containsKey(token)) return true;
        if (repeats != 0 || uiForeground || Config.protectedKey(key.key) || profile == null || !profile.enabled) return false;
        Config.Binding binding=profile.find(key.key,key.scan,key.vendor,key.product);
        if (binding == null || !binding.enabled()) return false;
        Pending prior=singles.remove(token);
        held.put(token,new Press(binding,now,prior != null && now < prior.due));
        return true;
    }
    public boolean up(Input key, long now, boolean canceled) {
        Press p=held.remove(key.token());
        tick(now);
        if (p == null) return false;
        if (canceled || p.canceled || p.fired) return true;
        if (p.binding.longAction.present() && now-p.down >= Config.LONG_MS) {emit(p.binding.longAction);return true;}
        if (p.binding.doubleAction.present()) {
            if (p.second) emit(p.binding.doubleAction);
            else singles.put(key.token(),new Pending(p.binding,now+Config.DOUBLE_MS));
        } else emit(p.binding.shortAction);
        return true;
    }
    public void tick(long now) {
        for (Press p : new ArrayList<>(held.values())) {
            if (!p.fired && !p.canceled && p.binding.longAction.present() && now-p.down >= Config.LONG_MS) {
                p.fired=true; emit(p.binding.longAction);
            }
        }
        for (String k : new ArrayList<>(singles.keySet())) {
            Pending p=singles.get(k);
            if (p != null && now >= p.due) { singles.remove(k); emit(p.binding.shortAction); }
        }
    }
    public long nextDeadline() {
        long next=Long.MAX_VALUE;
        for (Press p : held.values()) if (!p.fired && !p.canceled && p.binding.longAction.present()) next=Math.min(next,p.down+Config.LONG_MS);
        for (Pending p : singles.values()) next=Math.min(next,p.due);
        return next;
    }
    public void cancel() { setProfile(null); }
    private void emit(Config.Action action) { if (action.present()) sink.dispatch(action); }
}
