package fr.local.tv.sf463;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.media.tv.TvContract;
import android.provider.Settings;
import android.widget.Toast;
import fr.local.tv.sf463.core.Config;

final class Actions {
    static void perform(Context context,Config.Action action) {
        Intent intent;
        switch(action.type) {
            case "none":return;
            case "self":intent=new Intent(context,MainActivity.class);break;
            case "settings":intent=new Intent(Settings.ACTION_SETTINGS);break;
            case "couchy":intent=launch(context,"com.conreo.couchytv");break;
            case "app":intent=launch(context,action.packageName);break;
            case "hdmi1":case "hdmi2":
                String hardware="hdmi1".equals(action.type) ? "HW5" : "HW6";
                intent=new Intent(Intent.ACTION_VIEW,TvContract.buildChannelUriForPassthroughInput("com.mediatek.tvinput/.hdmi.HDMIInputService/"+hardware));
                intent.setComponent(new ComponentName("org.droidtv.playtv","org.droidtv.playtv.PlayTvActivity"));break;
            default: return;
        }
        if(intent==null) {Toast.makeText(context,"Application is not installed: "+action.packageName,Toast.LENGTH_LONG).show();return;}
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {context.startActivity(intent);} catch(RuntimeException failure) {
            Toast.makeText(context,"Cannot open "+action.toString(),Toast.LENGTH_LONG).show();
            android.util.Log.w("SF463","Action unavailable: "+action.type,failure);
        }
    }
    private static Intent launch(Context c,String pkg) {
        Intent i=c.getPackageManager().getLeanbackLaunchIntentForPackage(pkg);
        return i!=null ? i : c.getPackageManager().getLaunchIntentForPackage(pkg);
    }
    static String label(Config.Action a) {
        switch(a.type) {
            case "none": return "Off";
            case "hdmi1":return "HDMI 1";case "hdmi2":return "HDMI 2";
            case "couchy":return "Couchy home";case "settings":return "Android settings";case "self":return "Companion settings";
            default:return a.packageName;
        }
    }
}
