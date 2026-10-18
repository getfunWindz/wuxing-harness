package com.wuxing.shell.ui;

import android.app.Activity;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import com.wuxing.shell.R;

/** 连接配置屏：URL + 令牌；校验与持久化由 MainActivity 承担。 */
public final class ConfigScreen {
    public interface Listener {
        void onConnect(String url, String token);
    }

    private final View root;
    private final EditText urlInput;
    private final EditText tokenInput;
    private final TextView status;

    public ConfigScreen(Activity activity, Listener listener) {
        root = LayoutInflater.from(activity).inflate(R.layout.screen_config, null, false);
        urlInput = root.findViewById(R.id.input_url);
        tokenInput = root.findViewById(R.id.input_token);
        status = root.findViewById(R.id.status);
        ((Button) root.findViewById(R.id.btn_connect)).setOnClickListener(
                v -> listener.onConnect(urlInput.getText().toString(),
                        tokenInput.getText().toString()));
    }

    public View root() {
        return root;
    }

    public void setUrl(String url) {
        urlInput.setText(url);
    }

    public void setStatus(String text) {
        status.setText(text);
    }

    public void setTokenHint(String text) {
        tokenInput.setHint(text);
    }
}
