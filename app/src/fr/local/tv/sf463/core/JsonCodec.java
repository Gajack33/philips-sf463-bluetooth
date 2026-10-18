package fr.local.tv.sf463.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Small strict JSON codec: bounded input/depth, duplicate member rejection, schema versioning. */
public final class JsonCodec {
    public static final int MAX_CHARS=65536;
    private JsonCodec() {}
    public static Config decode(String text, boolean imported) {
        Object root=new Parser(text).parse(); Map<String,Object> m=object(root);
        if (integer(m,"schemaVersion") != Config.SCHEMA) throw new IllegalArgumentException("Unsupported schema version");
        Config c=new Config(); c.activeProfileId=string(m,"activeProfileId");
        for (Object entry : array(m,"profiles")) {
            Map<String,Object> p=object(entry);
            Config.Profile profile=new Config.Profile(string(p,"id"),string(p,"name"),bool(p,"enabled") && !imported);
            for (Object item : array(p,"bindings")) {
                Map<String,Object> b=object(item);
                Config.Button key=new Config.Button(integer(b,"keyCode"),integer(b,"scanCode"),integer(b,"vendorId"),integer(b,"productId"),string(b,"label"));
                profile.bindings.add(new Config.Binding(key,action(b.get("short")),action(b.get("long")),action(b.get("double"))));
            }
            c.profiles.add(profile);
        }
        c.validate(); return c;
    }
    private static Config.Action action(Object value) {
        Map<String,Object> a=object(value); String type=string(a,"type");
        return new Config.Action(type,a.containsKey("package") ? string(a,"package") : "");
    }
    public static String encode(Config c) {
        c.validate(); StringBuilder s=new StringBuilder();
        s.append("{\n  \"schemaVersion\":1,\n  \"activeProfileId\":").append(quote(c.activeProfileId)).append(",\n  \"profiles\":[");
        boolean first=true;
        for (Config.Profile p : c.profiles) {
            if (!first) s.append(','); first=false;
            s.append("\n    {\"id\":").append(quote(p.id)).append(",\"name\":").append(quote(p.name)).append(",\"enabled\":").append(p.enabled).append(",\"bindings\":[");
            boolean firstBinding=true;
            for (Config.Binding b : p.bindings) {
                if (!firstBinding) s.append(','); firstBinding=false;
                Config.Button k=b.button;
                s.append("\n      {\"keyCode\":").append(k.keyCode).append(",\"scanCode\":").append(k.scanCode).append(",\"vendorId\":").append(k.vendorId)
                    .append(",\"productId\":").append(k.productId).append(",\"label\":").append(quote(k.label)).append(",\"short\":").append(actionJson(b.shortAction))
                    .append(",\"long\":").append(actionJson(b.longAction)).append(",\"double\":").append(actionJson(b.doubleAction)).append('}');
            }
            s.append("\n    ]}");
        }
        return s.append("\n  ]\n}\n").toString();
    }
    private static String actionJson(Config.Action a) { return "{\"type\":"+quote(a.type)+("app".equals(a.type) ? ",\"package\":"+quote(a.packageName) : "")+"}"; }
    private static String quote(String value) {
        StringBuilder b=new StringBuilder("\"");
        for (int i=0;i<value.length();i++) {
            char ch=value.charAt(i);
            if (ch=='"' || ch=='\\') b.append('\\').append(ch);
            else if (ch<32) { String hex=Integer.toHexString(ch); b.append("\\u"); for(int j=hex.length();j<4;j++) b.append('0'); b.append(hex); }
            else b.append(ch);
        }
        return b.append('"').toString();
    }
    @SuppressWarnings("unchecked") private static Map<String,Object> object(Object o) {
        if (!(o instanceof Map)) throw new IllegalArgumentException("Expected JSON object"); return (Map<String,Object>)o;
    }
    @SuppressWarnings("unchecked") private static List<Object> array(Map<String,Object> m,String k) {
        Object o=m.get(k); if (!(o instanceof List)) throw new IllegalArgumentException("Expected array: "+k); return (List<Object>)o;
    }
    private static String string(Map<String,Object> m,String k) { Object o=m.get(k); if(!(o instanceof String)) throw new IllegalArgumentException("Expected string: "+k); return (String)o; }
    private static int integer(Map<String,Object> m,String k) { Object o=m.get(k); if(!(o instanceof Long) || (Long)o<Integer.MIN_VALUE || (Long)o>Integer.MAX_VALUE) throw new IllegalArgumentException("Expected integer: "+k); return ((Long)o).intValue(); }
    private static boolean bool(Map<String,Object> m,String k) { Object o=m.get(k); if(!(o instanceof Boolean)) throw new IllegalArgumentException("Expected boolean: "+k); return (Boolean)o; }

    private static final class Parser {
        final String s; int i;
        Parser(String s) { if(s==null || s.length()>MAX_CHARS) throw new IllegalArgumentException("Configuration is too large"); this.s=s; }
        Object parse() { Object x=value(0); white(); if(i!=s.length()) fail(); return x; }
        Object value(int depth) {
            if(depth>16) throw new IllegalArgumentException("JSON nesting is too deep"); white(); if(i>=s.length()) return fail(); char c=s.charAt(i);
            if(c=='{') {
                i++; Map<String,Object> m=new LinkedHashMap<>(); white(); if(take('}')) return m;
                do { white(); String k=quoted(); white(); expect(':'); Object v=value(depth+1); if(m.containsKey(k) || m.size()>=128) return fail(); m.put(k,v); white(); if(take('}')) return m; expect(','); } while(true);
            }
            if(c=='[') {
                i++; List<Object> a=new ArrayList<>(); white(); if(take(']')) return a;
                do { if(a.size()>=128) return fail(); a.add(value(depth+1)); white(); if(take(']')) return a; expect(','); } while(true);
            }
            if(c=='"') return quoted();
            if(s.startsWith("true",i)) {i+=4;return Boolean.TRUE;}
            if(s.startsWith("false",i)) {i+=5;return Boolean.FALSE;}
            if(s.startsWith("null",i)) {i+=4;return null;}
            int start=i; if(c=='-') i++; if(i>=s.length() || s.charAt(i)<'0' || s.charAt(i)>'9') return fail();
            if(s.charAt(i)=='0') i++; else while(i<s.length() && s.charAt(i)>='0' && s.charAt(i)<='9') i++;
            try {return Long.parseLong(s.substring(start,i));} catch(NumberFormatException e) {return fail();}
        }
        String quoted() {
            expect('"'); StringBuilder b=new StringBuilder();
            while(i<s.length()) {
                char c=s.charAt(i++); if(c=='"') return b.toString(); if(c<32) return fail();
                if(c=='\\') {
                    if(i>=s.length()) return fail(); c=s.charAt(i++);
                    switch(c) {
                        case '"': case '\\': case '/': b.append(c); break;
                        case 'b': b.append('\b');break; case 'f':b.append('\f');break;case 'n':b.append('\n');break;case 'r':b.append('\r');break;case 't':b.append('\t');break;
                        case 'u':
                            if(i+4>s.length()) return fail();
                            for(int j=i;j<i+4;j++) {char h=s.charAt(j);if(!((h>='0'&&h<='9')||(h>='a'&&h<='f')||(h>='A'&&h<='F')))return fail();}
                            b.append((char)Integer.parseInt(s.substring(i,i+4),16));i+=4;break;
                        default:return fail();
                    }
                } else b.append(c);
            }
            return fail();
        }
        void white() {while(i<s.length() && (s.charAt(i)==' ' || s.charAt(i)=='\n' || s.charAt(i)=='\r' || s.charAt(i)=='\t')) i++;}
        boolean take(char c) {if(i<s.length() && s.charAt(i)==c) {i++;return true;}return false;}
        void expect(char c) {if(!take(c)) fail();}
        <T>T fail() {throw new IllegalArgumentException("Invalid JSON near character "+i);}
    }
}
