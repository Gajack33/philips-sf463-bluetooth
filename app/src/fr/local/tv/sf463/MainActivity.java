package fr.local.tv.sf463;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.View;
import android.view.accessibility.AccessibilityManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import fr.local.tv.sf463.core.Config;
import fr.local.tv.sf463.core.JsonCodec;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;
import java.util.UUID;

/** Leanback-compatible native controls, local profiles and Storage Access Framework import/export. */
public final class MainActivity extends Activity {
    private static final int IMPORT=10, EXPORT=11;
    private Config config;
    private LinearLayout content;
    private boolean learning;
    private Config.Button learned;
    @Override public void onCreate(Bundle state) {super.onCreate(state);config=Store.load(this);render();}
    @Override protected void onResume() {super.onResume();UiState.foreground=true;if(config!=null) render();}
    @Override protected void onPause() {UiState.foreground=false;learning=false;learned=null;super.onPause();}
    private int dp(int value) {return Math.round(value*getResources().getDisplayMetrics().density);}
    private void render() {
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackgroundColor(Color.rgb(15,28,39));
        content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);content.setPadding(dp(48),dp(24),dp(48),dp(36));scroll.addView(content);setContentView(scroll);
        text("SF463 Companion",30,Color.WHITE);
        text("Local button shortcuts · 0.1.0",16,Color.rgb(154,185,205));
        Config.Profile profile=config.active();
        text("Profile: "+profile.name+" · "+(profile.enabled ? "ENABLED" : "DISABLED"),20,Color.WHITE);
        text(serviceEnabled() ? "Key filter is enabled in Android." : "Key filter is off. Android accessibility permission is optional and must be enabled manually.",15,Color.LTGRAY);
        if(learning) text("Press the button to learn. Essential keys stay available. Choose Cancel learning to stop.",18,Color.rgb(245,199,93));
        button(learning ? "Cancel learning" : "Learn a button",() -> {learning=!learning;learned=null;render();});
        button(profile.enabled ? "Disable this profile" : "Enable this profile",() -> {
            profile.enabled=!profile.enabled;save();
            if(profile.enabled && !serviceEnabled()) toast("Enable SF463 button shortcuts in Android Accessibility to use this profile.");
        });
        button("Android accessibility settings",() -> {try {startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));}catch(RuntimeException e){toast("Android accessibility settings are unavailable.");}});
        button("Profiles: select / create / duplicate / rename / delete",this::profileMenu);
        text("Buttons",22,Color.WHITE);
        if(profile.bindings.isEmpty()) text("No buttons yet. Learn a button to add one.",16,Color.LTGRAY);
        for(Config.Binding binding : profile.bindings) {
            String gestures="Short: "+Actions.label(binding.shortAction)+"   |   Hold: "+Actions.label(binding.longAction)+"   |   Double: "+Actions.label(binding.doubleAction);
            button(binding.button.label+"  ·  "+gestures,() -> editBinding(binding));
        }
        text("Hold: 600 ms. Optional double press: next DOWN within 300 ms after the first release. Double is off by default. Short actions run on release; enabling double delays a single action by 300 ms.",15,Color.LTGRAY);
        text("D-pad, OK/Enter, volume, power, Home, Back, voice and pairing pass through. Shortcuts pause while this app is open. HDMI actions target the verified Philips HW5/HW6 inputs.",15,Color.LTGRAY);
        button("Export profiles as JSON",() -> document(false));
        button("Import JSON (imported profiles start disabled)",() -> document(true));
        button("Reset to disabled color-button preset",() -> new AlertDialog.Builder(this).setTitle("Reset local profiles?")
            .setMessage("This replaces your profiles with the disabled preset: Red → Movix, Green → HDMI 1, Yellow → HDMI 2, Blue → Companion settings. Export first if you want a backup.")
            .setNegativeButton("Cancel",null).setPositiveButton("Reset",(d,w) -> {config=Config.defaults();save();}).show());
        text("No Internet permission, Bluetooth connection, screen-content access or background polling. Profiles stay on this TV unless you export them.",14,Color.rgb(154,185,205));
    }
    private void text(String value,int size,int color) {
        TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(color);v.setPadding(0,dp(8),0,dp(8));content.addView(v);
    }
    private void button(String label,Runnable click) {
        Button v=new Button(this);v.setText(label);v.setAllCaps(false);v.setTextSize(16);v.setMinHeight(dp(48));v.setFocusable(true);v.setOnClickListener(x -> click.run());
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.topMargin=dp(4);content.addView(v,params);
    }
    private void save() {try {config.validate();Store.save(this,config);render();}catch(IllegalArgumentException e){toast(e.getMessage());}}
    private void toast(String s) {Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    private boolean serviceEnabled() {
        AccessibilityManager manager=(AccessibilityManager)getSystemService(ACCESSIBILITY_SERVICE);
        if(manager==null) return false;
        for(AccessibilityServiceInfo service : manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK))
            if(service.getResolveInfo()!=null && getPackageName().equals(service.getResolveInfo().serviceInfo.packageName)) return true;
        return false;
    }
    @Override public boolean dispatchKeyEvent(KeyEvent e) {
        if(learned!=null && e.getKeyCode()==learned.keyCode && e.getScanCode()==learned.scanCode) {
            if(e.getAction()==KeyEvent.ACTION_UP) {
                Config.Button key=learned;learned=null;learning=false;
                Config.Profile p=config.active();Config.Binding previous=null;
                for(Config.Binding b:p.bindings) if(b.button.identity().equals(key.identity())) previous=b;
                if(previous!=null) {render();editBinding(previous);}
                else if(p.bindings.size()>=32) {toast("A profile can contain up to 32 buttons.");render();}
                else {Config.Binding b=new Config.Binding(key,Config.Action.none(),Config.Action.none(),Config.Action.none());p.bindings.add(b);save();editBinding(b);}
            }
            return true;
        }
        if(learning && e.getAction()==KeyEvent.ACTION_DOWN && e.getRepeatCount()==0) {
            if(Config.protectedKey(e.getKeyCode())) {toast("This essential key stays available and cannot be remapped.");return super.dispatchKeyEvent(e);}
            InputDevice device=e.getDevice();
            String name=KeyEvent.keyCodeToString(e.getKeyCode()).replace("KEYCODE_","");
            try {learned=new Config.Button(e.getKeyCode(),e.getScanCode(),device==null ? 0 : device.getVendorId(),device==null ? 0 : device.getProductId(),name);return true;}
            catch(IllegalArgumentException bad){toast(bad.getMessage());}
        }
        return super.dispatchKeyEvent(e);
    }
    private void profileMenu() {
        String[] options={"Select profile","Create empty profile","Duplicate current profile","Rename current profile","Delete current profile"};
        new AlertDialog.Builder(this).setTitle("Profiles").setItems(options,(d,which) -> {
            Config.Profile current=config.active();
            if(which==0) {
                String[] names=new String[config.profiles.size()];for(int i=0;i<names.length;i++) names[i]=config.profiles.get(i).name;
                new AlertDialog.Builder(this).setTitle("Select profile").setItems(names,(x,index) -> {config.activeProfileId=config.profiles.get(index).id;save();}).show();
            } else if(which==1 || which==2) {
                if(config.profiles.size()>=16) {toast("Keep at most 16 profiles.");return;}
                prompt("Profile name",which==2 ? current.name+" copy" : "New profile",name -> {
                    String id="p_"+UUID.randomUUID().toString().replace("-","");
                    Config.Profile added=which==2 ? current.copy(id,name) : new Config.Profile(id,name,false);
                    config.profiles.add(added);config.activeProfileId=id;save();
                });
            } else if(which==3) prompt("Rename profile",current.name,name -> {if(name.trim().isEmpty() || name.length()>40) throw new IllegalArgumentException("Use 1 to 40 characters");current.name=name.trim();save();});
            else if(config.profiles.size()==1) toast("Keep at least one profile; use Reset for the default preset.");
            else new AlertDialog.Builder(this).setTitle("Delete "+current.name+"?").setNegativeButton("Cancel",null).setPositiveButton("Delete",(x,w) -> {
                config.profiles.remove(current);config.activeProfileId=config.profiles.get(0).id;save();
            }).show();
        }).show();
    }
    private interface TextChoice {void apply(String value);}
    private void prompt(String title,String initial,TextChoice choice) {
        EditText input=new EditText(this);input.setSingleLine(true);input.setText(initial);input.selectAll();
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(title).setView(input).setNegativeButton("Cancel",null).setPositiveButton("Save",null).create();
        dialog.setOnShowListener(x -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {choice.apply(input.getText().toString());dialog.dismiss();}catch(IllegalArgumentException bad){input.setError(bad.getMessage());}
        }));dialog.show();
    }
    private void editBinding(Config.Binding b) {
        String identity="Key "+b.button.keyCode+", scan "+b.button.scanCode+", vendor/product "+b.button.vendorId+"/"+b.button.productId;
        String[] options={"Short · "+Actions.label(b.shortAction),"Hold (600 ms) · "+Actions.label(b.longAction),"Double (300 ms) · "+Actions.label(b.doubleAction),"Rename button","Remove button"};
        new AlertDialog.Builder(this).setTitle(b.button.label+" · "+identity).setItems(options,(d,which) -> {
            if(which<3) selectAction(which==0 ? b.shortAction : which==1 ? b.longAction : b.doubleAction,
                action -> {if(which==0)b.shortAction=action;else if(which==1)b.longAction=action;else b.doubleAction=action;save();});
            else if(which==3) prompt("Button label",b.button.label,name -> {
                Config.Button old=b.button;Config.Button key=new Config.Button(old.keyCode,old.scanCode,old.vendorId,old.productId,name);
                Config.Profile p=config.active();p.bindings.set(p.bindings.indexOf(b),new Config.Binding(key,b.shortAction,b.longAction,b.doubleAction));save();
            });
            else {config.active().bindings.remove(b);save();}
        }).show();
    }
    private interface ActionChoice {void apply(Config.Action action);}
    private void selectAction(Config.Action current,ActionChoice choice) {
        String[] labels={"Off","Movix","HDMI 1","HDMI 2","Couchy home","Android settings","Companion settings","Choose installed TV application…"};
        Config.Action[] actions={Config.Action.none(),new Config.Action("app","com.movix.tv"),new Config.Action("hdmi1",""),new Config.Action("hdmi2",""),new Config.Action("couchy",""),new Config.Action("settings",""),new Config.Action("self","")};
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Action · "+Actions.label(current))
            .setItems(labels,(d,which) -> {if(which<actions.length)choice.apply(actions[which]);else selectApp(choice);})
            .setNeutralButton("Test action",(d,w) -> Actions.perform(this,current)).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setEnabled(!"none".equals(current.type)));
        dialog.show();
    }
    private void selectApp(ActionChoice choice) {
        Intent launcher=new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LEANBACK_LAUNCHER);
        List<ResolveInfo> installed=getPackageManager().queryIntentActivities(launcher,0);
        TreeMap<String,String> apps=new TreeMap<>();
        for(ResolveInfo r:installed) {String pkg=r.activityInfo.packageName;apps.put(r.loadLabel(getPackageManager()).toString()+" · "+pkg,pkg);}
        if(apps.isEmpty()) {toast("No TV applications found.");return;}
        List<String> names=new ArrayList<>(apps.keySet());
        new AlertDialog.Builder(this).setTitle("Installed TV applications").setItems(names.toArray(new String[0]),(d,which) -> choice.apply(new Config.Action("app",apps.get(names.get(which))))).show();
    }
    private void document(boolean imported) {
        Intent i=new Intent(imported ? Intent.ACTION_OPEN_DOCUMENT : Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE);
        if(!imported) i.putExtra(Intent.EXTRA_TITLE,"sf463-profiles-v1.json");
        ResolveInfo handler=getPackageManager().resolveActivity(i,0);
        if(handler==null || handler.activityInfo==null || handler.activityInfo.packageName.startsWith("com.android.tv.frameworkpackagestubs")) {
            jsonTextDialog(imported);return;
        }
        try {startActivityForResult(i,imported ? IMPORT : EXPORT);}catch(RuntimeException unavailable){jsonTextDialog(imported);}
    }
    /** Android TV can advertise a placeholder document picker. Explicit local
     * clipboard/text exchange still works without granting storage access. */
    private void jsonTextDialog(boolean imported) {
        EditText input=new EditText(this);input.setSingleLine(false);input.setMinLines(6);input.setMaxLines(10);
        input.setTextSize(12);input.setTypeface(Typeface.MONOSPACE);input.setHorizontallyScrolling(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        input.setHint("Paste a schemaVersion 1 configuration");
        if(!imported) {input.setText(JsonCodec.encode(config));input.setKeyListener(null);input.setTextIsSelectable(true);}
        AlertDialog.Builder builder=new AlertDialog.Builder(this).setTitle(imported ? "Import JSON text" : "Export JSON text")
            .setMessage("This TV has no document picker. Use JSON text instead.").setView(input)
            .setNegativeButton(imported ? "Cancel" : "Close",null).setPositiveButton(imported ? "Import disabled profiles" : "Copy",null);
        if(imported) builder.setNeutralButton("Paste",null);
        AlertDialog dialog=builder.create();
        dialog.setOnShowListener(x -> {
            if(imported) dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> {
                ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
                ClipData clip=clipboard==null ? null : clipboard.getPrimaryClip();
                CharSequence text=clip==null || clip.getItemCount()==0 ? null : clip.getItemAt(0).getText();
                if(text==null) {toast("Clipboard has no JSON text.");return;}
                if(text.length()>JsonCodec.MAX_CHARS) {input.setError("Configuration is too large");return;}
                input.setText(text);input.setSelection(input.length());
            });
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                if(imported) {
                    try {Config next=JsonCodec.decode(input.getText().toString(),true);config=next;save();dialog.dismiss();toast("Profiles imported and disabled.");}
                    catch(IllegalArgumentException bad){input.setError(bad.getMessage());}
                } else {
                    ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
                    if(clipboard!=null) {clipboard.setPrimaryClip(ClipData.newPlainText("SF463 profiles",input.getText()));toast("JSON copied to the TV clipboard.");}
                }
            });
        });
        dialog.show();
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(result!=RESULT_OK || data==null || data.getData()==null || (request!=IMPORT && request!=EXPORT))return;
        Uri uri=data.getData();String export=request==EXPORT ? JsonCodec.encode(config) : null;
        new Thread(() -> {
            try {
                if(request==IMPORT) {
                    ByteArrayOutputStream output=new ByteArrayOutputStream();
                    try(InputStream in=getContentResolver().openInputStream(uri)) {
                        if(in==null)throw new IllegalArgumentException("Cannot open document");byte[] buffer=new byte[4096];int n;
                        while((n=in.read(buffer))!=-1) {if(output.size()+n>JsonCodec.MAX_CHARS*4)throw new IllegalArgumentException("Configuration is too large");output.write(buffer,0,n);}
                    }
                    String source=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(output.toByteArray())).toString();
                    Config imported=JsonCodec.decode(source,true);
                    runOnUiThread(() -> {config=imported;save();toast("Profiles imported and disabled. Review them before enabling.");});
                } else {
                    try(OutputStream out=getContentResolver().openOutputStream(uri,"wt")) {if(out==null)throw new IllegalArgumentException("Cannot write document");out.write(export.getBytes(StandardCharsets.UTF_8));}
                    runOnUiThread(() -> toast("Profiles exported."));
                }
            } catch(Exception error) {runOnUiThread(() -> toast("Document operation failed: "+error.getMessage()));}
        },"sf463-document").start();
    }
}
