package fr.local.tv.sf463;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;
import fr.local.tv.sf463.core.GestureEngine;

/** Optional event-driven filter. No screen reads, Bluetooth access, network or polling. */
public final class RemoteKeyService extends AccessibilityService implements SharedPreferences.OnSharedPreferenceChangeListener {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final GestureEngine engine=new GestureEngine(action -> Actions.perform(this,action));
    private final Runnable deadline=() -> {engine.tick(SystemClock.uptimeMillis());schedule();};
    @Override protected void onServiceConnected() {
        AccessibilityServiceInfo info=getServiceInfo();
        if(info!=null) {info.eventTypes=0;info.flags=AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS;setServiceInfo(info);}
        Store.preferences(this).registerOnSharedPreferenceChangeListener(this);reload();
    }
    private void reload() {engine.setProfile(Store.load(this).active());schedule();}
    @Override public void onSharedPreferenceChanged(SharedPreferences prefs,String key) {if(Store.KEY.equals(key)) reload();}
    @Override protected boolean onKeyEvent(KeyEvent event) {
        InputDevice device=event.getDevice();
        GestureEngine.Input input=new GestureEngine.Input(event.getDeviceId(),event.getKeyCode(),event.getScanCode(),device==null ? 0 : device.getVendorId(),device==null ? 0 : device.getProductId());
        boolean consumed;
        if(event.getAction()==KeyEvent.ACTION_DOWN) consumed=engine.down(input,event.getRepeatCount(),event.getEventTime(),UiState.foreground);
        else if(event.getAction()==KeyEvent.ACTION_UP) consumed=engine.up(input,event.getEventTime(),event.isCanceled());
        else return false;
        schedule();return consumed;
    }
    private void schedule() {
        handler.removeCallbacks(deadline);long at=engine.nextDeadline();
        if(at!=Long.MAX_VALUE) handler.postAtTime(deadline,Math.max(at,SystemClock.uptimeMillis()));
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) { /* No window events requested or examined. */ }
    @Override public void onInterrupt() {engine.cancel();handler.removeCallbacks(deadline);}
    @Override public void onDestroy() {
        Store.preferences(this).unregisterOnSharedPreferenceChangeListener(this);engine.cancel();handler.removeCallbacksAndMessages(null);super.onDestroy();
    }
}
